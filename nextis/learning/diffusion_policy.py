"""Minimal DDPM-based Diffusion Policy for action prediction.

Predicts action chunks by iteratively denoising random noise conditioned
on the current observation. Uses a cosine noise schedule and an MLP
denoising network.

This is a minimal implementation — proof of concept for the training
pipeline. Production use should consider UNet or Transformer architectures.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from dataclasses import dataclass
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


class DiffusionSchedule:
    """Cosine noise schedule for DDPM.

    Args:
        num_steps: Number of diffusion timesteps.
    """

    def __init__(self, num_steps: int = 100) -> None:
        self.num_steps = num_steps
        # Cosine schedule (Nichol & Dhariwal, 2021)
        steps = torch.arange(num_steps + 1, dtype=torch.float64)
        f = torch.cos((steps / num_steps + 0.008) / 1.008 * math.pi / 2) ** 2
        alpha_cumprod = f / f[0]
        betas = 1 - alpha_cumprod[1:] / alpha_cumprod[:-1]
        self.betas = torch.clamp(betas, max=0.999).float()
        self.alphas = (1.0 - self.betas).float()
        self.alpha_cumprod = torch.cumprod(self.alphas, dim=0).float()
        self.sqrt_alpha_cumprod = torch.sqrt(self.alpha_cumprod)
        self.sqrt_one_minus_alpha_cumprod = torch.sqrt(1.0 - self.alpha_cumprod)

    def add_noise(self, x0: torch.Tensor, noise: torch.Tensor, t: torch.Tensor) -> torch.Tensor:
        """Add noise to data at timestep t: q(x_t | x_0)."""
        sqrt_a = self.sqrt_alpha_cumprod[t].view(-1, 1, 1)
        sqrt_1ma = self.sqrt_one_minus_alpha_cumprod[t].view(-1, 1, 1)
        return sqrt_a * x0 + sqrt_1ma * noise


class DiffusionPolicy(nn.Module):
    """Denoising network conditioned on observation and timestep.

    Architecture: obs + noisy_action + timestep_embed → MLP → predicted noise.

    Args:
        obs_dim: Observation vector size.
        action_dim: Action vector size.
        chunk_size: Number of future actions to predict.
        hidden_dim: MLP hidden layer size.
        num_diffusion_steps: Number of diffusion timesteps.
    """

    def __init__(
        self,
        obs_dim: int,
        action_dim: int,
        chunk_size: int = 10,
        hidden_dim: int = 256,
        num_diffusion_steps: int = 100,
    ) -> None:
        super().__init__()
        self.chunk_size = chunk_size
        self.action_dim = action_dim
        action_flat = action_dim * chunk_size

        # Timestep sinusoidal embedding
        self.time_embed = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim),
            nn.SiLU(),
            nn.Linear(hidden_dim, hidden_dim),
        )
        self.time_dim = hidden_dim

        # Observation projection
        self.obs_proj = nn.Linear(obs_dim, hidden_dim)

        # Action projection (flattened chunk)
        self.action_proj = nn.Linear(action_flat, hidden_dim)

        # Denoising MLP
        self.net = nn.Sequential(
            nn.Linear(hidden_dim * 3, hidden_dim * 2),
            nn.SiLU(),
            nn.Linear(hidden_dim * 2, hidden_dim * 2),
            nn.SiLU(),
            nn.Linear(hidden_dim * 2, action_flat),
        )

    def _sinusoidal_embedding(self, t: torch.Tensor) -> torch.Tensor:
        """Sinusoidal timestep embedding."""
        half_dim = self.time_dim // 2
        emb = math.log(10000) / (half_dim - 1)
        emb = torch.exp(torch.arange(half_dim, device=t.device, dtype=torch.float32) * -emb)
        emb = t.float().unsqueeze(1) * emb.unsqueeze(0)
        return torch.cat([torch.sin(emb), torch.cos(emb)], dim=1)

    def forward(
        self, obs: torch.Tensor, noisy_action: torch.Tensor, timestep: torch.Tensor
    ) -> torch.Tensor:
        """Predict noise in the noisy action.

        Args:
            obs: Observation of shape ``(B, obs_dim)``.
            noisy_action: Noisy action chunk ``(B, chunk_size, action_dim)``.
            timestep: Diffusion timestep ``(B,)`` as integer indices.

        Returns:
            Predicted noise ``(B, chunk_size, action_dim)``.
        """
        B = obs.shape[0]
        t_emb = self.time_embed(self._sinusoidal_embedding(timestep))
        obs_emb = self.obs_proj(obs)
        act_flat = noisy_action.view(B, -1)
        act_emb = self.action_proj(act_flat)

        h = torch.cat([obs_emb, act_emb, t_emb], dim=1)
        out = self.net(h)
        return out.view(B, self.chunk_size, self.action_dim)


class DiffusionInferenceWrapper:
    """Wraps a trained DiffusionPolicy for inference via DDPM sampling.

    Provides the same ``predict()`` API as the ACT ``Policy`` class.

    Args:
        model: Trained DiffusionPolicy in eval mode.
        config: Checkpoint config dict.
        schedule: Noise schedule used during training.
    """

    def __init__(self, model: DiffusionPolicy, config: dict, schedule: DiffusionSchedule) -> None:
        self._model = model
        self._config = config
        self._schedule = schedule

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
        """Run DDPM sampling to generate actions from observation.

        Args:
            observation: Dict mapping joint names to float values.

        Returns:
            Action array of shape ``(chunk_size, action_dim)``.
        """
        keys = self._config.get("joint_keys") or sorted(observation)
        obs = torch.tensor([observation[k] for k in keys], dtype=torch.float32).unsqueeze(0)

        sched = self._schedule
        x = torch.randn(1, self.chunk_size, self.action_dim)

        with torch.no_grad():
            for t_idx in reversed(range(sched.num_steps)):
                t = torch.tensor([t_idx])
                pred_noise = self._model(obs, x, t)
                alpha = sched.alphas[t_idx]
                alpha_cum = sched.alpha_cumprod[t_idx]
                beta = sched.betas[t_idx]
                x = (1 / torch.sqrt(alpha)) * (x - (beta / torch.sqrt(1 - alpha_cum)) * pred_noise)
                if t_idx > 0:
                    x = x + torch.sqrt(beta) * torch.randn_like(x)

        return x[0].numpy()


@dataclass
class DiffusionConfig:
    """Configuration for diffusion policy training."""

    num_epochs: int = 100
    batch_size: int = 32
    learning_rate: float = 1e-4
    chunk_size: int = 10
    hidden_dim: int = 256
    num_diffusion_steps: int = 100


class DiffusionTrainer:
    """Trains a DiffusionPolicy using DDPM noise-prediction loss.

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
        """Train a DiffusionPolicy on the given dataset.

        Args:
            dataset_info: Output from StepDataset.build().
            config: Training hyperparameters.
            on_progress: Epoch-level progress callback.
            should_cancel: Returns True to request cancellation.

        Returns:
            TrainingResult with checkpoint path and final loss.
        """
        cfg = config or TrainingConfig()
        num_diffusion_steps = getattr(cfg, "num_diffusion_steps", 100)

        try:
            train_obs = np.load(dataset_info.output_dir / "train_obs.npy")
            train_act = np.load(dataset_info.output_dir / "train_act.npy")
            val_obs = np.load(dataset_info.output_dir / "val_obs.npy")
            val_act = np.load(dataset_info.output_dir / "val_act.npy")
        except Exception as e:
            raise TrainingError(f"Failed to load dataset: {e}") from e

        obs_dim = train_obs.shape[1]
        action_dim = train_act.shape[1]
        schedule = DiffusionSchedule(num_diffusion_steps)

        model = DiffusionPolicy(
            obs_dim, action_dim, cfg.chunk_size, cfg.hidden_dim, num_diffusion_steps
        )
        optimizer = torch.optim.Adam(model.parameters(), lr=cfg.learning_rate)

        # Build action chunks from sequential data
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
            "Training DiffusionPolicy: obs=%d, act=%d, epochs=%d, diffusion_steps=%d",
            obs_dim,
            action_dim,
            cfg.num_epochs,
            num_diffusion_steps,
        )

        final_loss = 0.0
        model.train()

        for epoch in range(cfg.num_epochs):
            total_loss = 0.0
            num_batches = 0

            for obs_batch, act_batch in loader:
                B = obs_batch.shape[0]
                noise = torch.randn_like(act_batch)
                t = torch.randint(0, num_diffusion_steps, (B,))
                noisy = schedule.add_noise(act_batch, noise, t)
                pred_noise = model(obs_batch, noisy, t)
                loss = F.mse_loss(pred_noise, noise)
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
                    noise_v = torch.randn_like(val_act_t)
                    t_v = torch.randint(0, num_diffusion_steps, (B_val,))
                    noisy_v = schedule.add_noise(val_act_t, noise_v, t_v)
                    pred_v = model(val_obs_t, noisy_v, t_v)
                    val_loss = float(F.mse_loss(pred_v, noise_v).item())
                model.train()

            if on_progress:
                on_progress(TrainingProgress(epoch, cfg.num_epochs, avg_loss, val_loss))

            if should_cancel and should_cancel():
                logger.info("Diffusion training cancelled at epoch %d", epoch)
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
                    "architecture": "diffusion",
                    "num_diffusion_steps": num_diffusion_steps,
                    "joint_keys": dataset_info.joint_keys,
                },
            },
            str(ckpt_path),
        )

        logger.info("Diffusion checkpoint saved: %s (loss=%.6f)", ckpt_path, final_loss)
        return TrainingResult(ckpt_path, final_loss, cfg.num_epochs)


def _build_chunks(
    obs: np.ndarray, act: np.ndarray, chunk_size: int
) -> tuple[np.ndarray, np.ndarray]:
    """Build observation-action_chunk pairs from sequential data.

    For each timestep i, the chunk is act[i:i+chunk_size]. If fewer than
    chunk_size steps remain, the last action is repeated to pad.

    Returns:
        Tuple of (obs_array, act_chunks) where act_chunks has shape
        ``(N, chunk_size, action_dim)``.
    """
    n = len(obs)
    action_dim = act.shape[1]
    chunks = np.zeros((n, chunk_size, action_dim), dtype=np.float32)
    for i in range(n):
        end = min(i + chunk_size, n)
        chunk_len = end - i
        chunks[i, :chunk_len] = act[i:end]
        if chunk_len < chunk_size:
            chunks[i, chunk_len:] = act[end - 1]
    return obs, chunks
