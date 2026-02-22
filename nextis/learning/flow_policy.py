"""Minimal flow matching policy (PI0.5-style) for action prediction.

Uses conditional flow matching to learn a velocity field that maps
noise to action chunks. Simpler than DDPM — no noise schedule needed.
Inference uses Euler integration from noise to data.

Reference: Lipman et al., "Flow Matching for Generative Modeling" (2023).
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, TensorDataset

from nextis.errors import TrainingError
from nextis.learning.dataset import DatasetInfo
from nextis.learning.trainer import TrainingConfig, TrainingProgress, TrainingResult

logger = logging.getLogger(__name__)


class FlowPolicy(nn.Module):
    """Flow matching network — predicts the velocity field from noise to action.

    Architecture: obs_proj + time_embed + action_proj → MLP → velocity.

    Args:
        obs_dim: Observation vector size.
        action_dim: Action vector size.
        chunk_size: Number of future actions to predict.
        hidden_dim: MLP hidden layer size.
    """

    def __init__(
        self,
        obs_dim: int,
        action_dim: int,
        chunk_size: int = 10,
        hidden_dim: int = 256,
    ) -> None:
        super().__init__()
        self.chunk_size = chunk_size
        self.action_dim = action_dim
        action_flat = action_dim * chunk_size

        # Time embedding (sinusoidal + MLP)
        self.time_dim = hidden_dim
        self.time_embed = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim),
            nn.SiLU(),
            nn.Linear(hidden_dim, hidden_dim),
        )

        # Observation and action projections
        self.obs_proj = nn.Linear(obs_dim, hidden_dim)
        self.action_proj = nn.Linear(action_flat, hidden_dim)

        # Velocity prediction MLP
        self.net = nn.Sequential(
            nn.Linear(hidden_dim * 3, hidden_dim * 2),
            nn.SiLU(),
            nn.Linear(hidden_dim * 2, hidden_dim * 2),
            nn.SiLU(),
            nn.Linear(hidden_dim * 2, action_flat),
        )

    def _sinusoidal_embedding(self, t: torch.Tensor) -> torch.Tensor:
        """Sinusoidal time embedding for continuous t in [0, 1]."""
        half_dim = self.time_dim // 2
        emb = math.log(10000) / (half_dim - 1)
        emb = torch.exp(torch.arange(half_dim, device=t.device, dtype=torch.float32) * -emb)
        emb = t.float().unsqueeze(1) * emb.unsqueeze(0)
        return torch.cat([torch.sin(emb), torch.cos(emb)], dim=1)

    def forward(self, obs: torch.Tensor, x_t: torch.Tensor, t: torch.Tensor) -> torch.Tensor:
        """Predict the velocity field at (x_t, t).

        Args:
            obs: Observation of shape ``(B, obs_dim)``.
            x_t: Interpolated point ``(B, chunk_size, action_dim)``.
            t: Continuous time ``(B,)`` in [0, 1].

        Returns:
            Predicted velocity ``(B, chunk_size, action_dim)``.
        """
        B = obs.shape[0]
        t_emb = self.time_embed(self._sinusoidal_embedding(t))
        obs_emb = self.obs_proj(obs)
        act_flat = x_t.view(B, -1)
        act_emb = self.action_proj(act_flat)

        h = torch.cat([obs_emb, act_emb, t_emb], dim=1)
        out = self.net(h)
        return out.view(B, self.chunk_size, self.action_dim)


class FlowInferenceWrapper:
    """Wraps a trained FlowPolicy for inference via Euler integration.

    Provides the same ``predict()`` API as the ACT ``Policy`` class.

    Args:
        model: Trained FlowPolicy in eval mode.
        config: Checkpoint config dict.
    """

    def __init__(self, model: FlowPolicy, config: dict) -> None:
        self._model = model
        self._config = config
        self._num_flow_steps = config.get("num_flow_steps", 20)

    @property
    def chunk_size(self) -> int:
        return self._config["chunk_size"]

    @property
    def obs_dim(self) -> int:
        return self._config["obs_dim"]

    @property
    def action_dim(self) -> int:
        return self._config["action_dim"]

    @property
    def joint_keys(self) -> list[str]:
        return self._config.get("joint_keys", [])

    def predict(self, observation: dict[str, float]) -> np.ndarray:
        """Generate actions by integrating the flow from noise to data.

        Uses Euler integration with ``num_flow_steps`` steps.

        Args:
            observation: Dict mapping joint names to float values.

        Returns:
            Action array of shape ``(chunk_size, action_dim)``.
        """
        keys = self._config.get("joint_keys") or sorted(observation)
        obs = torch.tensor([observation[k] for k in keys], dtype=torch.float32).unsqueeze(0)

        # Start from pure noise (t=0)
        x = torch.randn(1, self.chunk_size, self.action_dim)
        dt = 1.0 / self._num_flow_steps

        with torch.no_grad():
            for step in range(self._num_flow_steps):
                t = torch.tensor([step * dt])
                v = self._model(obs, x, t)
                x = x + dt * v  # Euler step

        return x[0].numpy()


class FlowTrainer:
    """Trains a FlowPolicy using conditional flow matching loss.

    The training objective is simple: at a random time t, the model
    predicts the velocity = (x1 - x0) for the linear interpolation
    x_t = (1-t)*x0 + t*x1, where x0 is noise and x1 is data.

    Args:
        policies_dir: Root directory for saving checkpoints.
    """

    def __init__(self, policies_dir: str | Path = "data/policies") -> None:
        self._policies_dir = Path(policies_dir)

    async def train(
        self,
        dataset_info: DatasetInfo,
        config: TrainingConfig | None = None,
        on_progress: Callable[[TrainingProgress], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> TrainingResult:
        """Train a FlowPolicy on the given dataset.

        Args:
            dataset_info: Output from StepDataset.build().
            config: Training hyperparameters.
            on_progress: Epoch-level progress callback.
            should_cancel: Returns True to request cancellation.

        Returns:
            TrainingResult with checkpoint path and final loss.
        """
        cfg = config or TrainingConfig()
        num_flow_steps = getattr(cfg, "num_flow_steps", 20)

        try:
            train_obs = np.load(dataset_info.output_dir / "train_obs.npy")
            train_act = np.load(dataset_info.output_dir / "train_act.npy")
            val_obs = np.load(dataset_info.output_dir / "val_obs.npy")
            val_act = np.load(dataset_info.output_dir / "val_act.npy")
        except Exception as e:
            raise TrainingError(f"Failed to load dataset: {e}") from e

        obs_dim = train_obs.shape[1]
        action_dim = train_act.shape[1]

        model = FlowPolicy(obs_dim, action_dim, cfg.chunk_size, cfg.hidden_dim)
        optimizer = torch.optim.Adam(model.parameters(), lr=cfg.learning_rate)

        # Build action chunks from sequential data
        from nextis.learning.diffusion_policy import _build_chunks

        chunk_obs, chunk_act = _build_chunks(train_obs, train_act, cfg.chunk_size)
        loader = DataLoader(
            TensorDataset(
                torch.tensor(chunk_obs, dtype=torch.float32),
                torch.tensor(chunk_act, dtype=torch.float32),
            ),
            batch_size=cfg.batch_size,
            shuffle=True,
        )

        has_val = len(val_obs) > 0
        if has_val:
            val_chunk_obs, val_chunk_act = _build_chunks(val_obs, val_act, cfg.chunk_size)
            val_obs_t = torch.tensor(val_chunk_obs, dtype=torch.float32)
            val_act_t = torch.tensor(val_chunk_act, dtype=torch.float32)

        logger.info(
            "Training FlowPolicy (PI0.5): obs=%d, act=%d, epochs=%d, flow_steps=%d",
            obs_dim,
            action_dim,
            cfg.num_epochs,
            num_flow_steps,
        )

        final_loss = 0.0
        model.train()

        for epoch in range(cfg.num_epochs):
            total_loss = 0.0
            num_batches = 0

            for obs_batch, act_batch in loader:
                B = obs_batch.shape[0]
                # Sample random time t ∈ [0, 1]
                t = torch.rand(B)
                # Sample noise x0
                x0 = torch.randn_like(act_batch)
                # Linear interpolation: x_t = (1-t)*x0 + t*x1
                t_expand = t.view(B, 1, 1)
                x_t = (1 - t_expand) * x0 + t_expand * act_batch
                # Target velocity: v = x1 - x0
                target_v = act_batch - x0
                # Predict velocity
                pred_v = model(obs_batch, x_t, t)
                loss = F.mse_loss(pred_v, target_v)
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()
                total_loss += loss.item()
                num_batches += 1

            avg_loss = total_loss / max(num_batches, 1)
            final_loss = avg_loss

            val_loss: float | None = None
            if has_val:
                model.eval()
                with torch.no_grad():
                    B_val = val_obs_t.shape[0]
                    t_v = torch.rand(B_val)
                    x0_v = torch.randn_like(val_act_t)
                    t_v_expand = t_v.view(B_val, 1, 1)
                    x_t_v = (1 - t_v_expand) * x0_v + t_v_expand * val_act_t
                    target_v_v = val_act_t - x0_v
                    pred_v_v = model(val_obs_t, x_t_v, t_v)
                    val_loss = float(F.mse_loss(pred_v_v, target_v_v).item())
                model.train()

            if on_progress:
                on_progress(TrainingProgress(epoch, cfg.num_epochs, avg_loss, val_loss))

            if should_cancel and should_cancel():
                logger.info("Flow training cancelled at epoch %d", epoch)
                raise TrainingError("Training cancelled by user")

            if epoch % 10 == 0 or epoch == cfg.num_epochs - 1:
                val_str = f", val={val_loss:.6f}" if val_loss is not None else ""
                logger.info("Epoch %d/%d: loss=%.6f%s", epoch, cfg.num_epochs, avg_loss, val_str)

        # Save checkpoint
        ckpt_dir = self._policies_dir / dataset_info.assembly_id / dataset_info.step_id
        ckpt_dir.mkdir(parents=True, exist_ok=True)
        ckpt_path = ckpt_dir / "policy.pt"

        torch.save(
            {
                "model_state_dict": model.state_dict(),
                "config": {
                    "obs_dim": obs_dim,
                    "action_dim": action_dim,
                    "chunk_size": cfg.chunk_size,
                    "hidden_dim": cfg.hidden_dim,
                    "architecture": "pi0",
                    "num_flow_steps": num_flow_steps,
                    "joint_keys": dataset_info.joint_keys,
                },
            },
            str(ckpt_path),
        )

        logger.info("Flow checkpoint saved: %s (loss=%.6f)", ckpt_path, final_loss)
        return TrainingResult(ckpt_path, final_loss, cfg.num_epochs)
