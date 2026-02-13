"""Minimal ACT policy trainer — proves the training pipeline end-to-end.

This is NOT production quality. It's the simplest possible implementation
that produces a real checkpoint. LeRobot's ACT is much better. But this
proves the full pipeline works: HDF5 demos → dataset → training → checkpoint
→ inference.
"""

from __future__ import annotations

import logging
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

logger = logging.getLogger(__name__)


@dataclass
class TrainingConfig:
    """Configuration for a training run.

    Attributes:
        num_epochs: Number of training epochs.
        batch_size: Mini-batch size.
        learning_rate: Adam optimizer learning rate.
        chunk_size: Number of future actions predicted per step.
        hidden_dim: Transformer hidden dimension.
    """

    num_epochs: int = 100
    batch_size: int = 32
    learning_rate: float = 1e-4
    chunk_size: int = 10
    hidden_dim: int = 128


@dataclass
class TrainingProgress:
    """Progress update emitted during training.

    Attributes:
        epoch: Current epoch (0-indexed).
        total_epochs: Total number of epochs.
        loss: Training loss for this epoch.
        val_loss: Validation loss, if computed.
    """

    epoch: int
    total_epochs: int
    loss: float
    val_loss: float | None = None


@dataclass
class TrainingResult:
    """Final result of a completed training run.

    Attributes:
        checkpoint_path: Path to the saved model checkpoint.
        final_loss: Training loss at the last epoch.
        epochs_trained: Number of epochs actually trained.
    """

    checkpoint_path: Path
    final_loss: float
    epochs_trained: int


class MinimalACT(nn.Module):
    """Minimal Action Chunking Transformer.

    Predicts a chunk of future actions from a single observation vector.
    Architecture: obs_proj → TransformerEncoder → action_head.

    Args:
        obs_dim: Observation vector size (e.g. number of joints).
        action_dim: Action vector size (e.g. number of joints).
        chunk_size: Number of future actions to predict.
        hidden_dim: Internal transformer dimension.
    """

    def __init__(
        self,
        obs_dim: int,
        action_dim: int,
        chunk_size: int = 10,
        hidden_dim: int = 128,
    ) -> None:
        super().__init__()
        self.obs_proj = nn.Linear(obs_dim, hidden_dim)
        self.encoder = nn.TransformerEncoder(
            nn.TransformerEncoderLayer(
                d_model=hidden_dim, nhead=4, batch_first=True, dim_feedforward=hidden_dim * 2
            ),
            num_layers=2,
        )
        self.action_head = nn.Linear(hidden_dim, action_dim * chunk_size)
        self.chunk_size = chunk_size
        self.action_dim = action_dim

    def forward(self, obs: torch.Tensor) -> torch.Tensor:
        """Forward pass.

        Args:
            obs: Observation tensor of shape ``(B, obs_dim)``.

        Returns:
            Action chunks of shape ``(B, chunk_size, action_dim)``.
        """
        h = self.obs_proj(obs).unsqueeze(1)  # (B, 1, hidden)
        h = self.encoder(h)  # (B, 1, hidden)
        actions = self.action_head(h[:, 0])  # (B, action_dim * chunk_size)
        return actions.view(-1, self.chunk_size, self.action_dim)


class PolicyTrainer:
    """Trains a MinimalACT policy from pre-built numpy datasets.

    Example::

        info = StepDataset("gearbox", "step_001").build()
        trainer = PolicyTrainer()
        result = await trainer.train(info)
        print(result.checkpoint_path)
    """

    def __init__(self, policies_dir: str = "data/policies") -> None:
        self._policies_dir = Path(policies_dir)

    async def train(
        self,
        dataset_info: DatasetInfo,
        config: TrainingConfig | None = None,
        on_progress: Callable[[TrainingProgress], None] | None = None,
    ) -> TrainingResult:
        """Train a MinimalACT policy on the given dataset.

        Args:
            dataset_info: Output from StepDataset.build().
            config: Training hyperparameters (uses defaults if None).
            on_progress: Optional callback for epoch-level progress updates.

        Returns:
            TrainingResult with checkpoint path and final loss.

        Raises:
            TrainingError: If training data cannot be loaded.
        """
        cfg = config or TrainingConfig()

        try:
            train_obs = np.load(dataset_info.output_dir / "train_obs.npy")
            train_act = np.load(dataset_info.output_dir / "train_act.npy")
            val_obs = np.load(dataset_info.output_dir / "val_obs.npy")
            val_act = np.load(dataset_info.output_dir / "val_act.npy")
        except Exception as e:
            raise TrainingError(f"Failed to load dataset: {e}") from e

        obs_dim = train_obs.shape[1]
        action_dim = train_act.shape[1]

        model = MinimalACT(obs_dim, action_dim, cfg.chunk_size, cfg.hidden_dim)
        optimizer = torch.optim.Adam(model.parameters(), lr=cfg.learning_rate)

        train_dataset = TensorDataset(
            torch.tensor(train_obs, dtype=torch.float32),
            torch.tensor(train_act, dtype=torch.float32),
        )
        loader = DataLoader(train_dataset, batch_size=cfg.batch_size, shuffle=True)

        # Validation tensors (may be empty if dataset is very small)
        has_val = len(val_obs) > 0
        if has_val:
            val_obs_t = torch.tensor(val_obs, dtype=torch.float32)
            val_act_t = torch.tensor(val_act, dtype=torch.float32)

        logger.info(
            "Training MinimalACT: obs_dim=%d, act_dim=%d, epochs=%d, train=%d, val=%d",
            obs_dim,
            action_dim,
            cfg.num_epochs,
            len(train_obs),
            len(val_obs),
        )

        final_loss = 0.0
        model.train()

        for epoch in range(cfg.num_epochs):
            total_loss = 0.0
            num_batches = 0

            for obs_batch, act_batch in loader:
                pred = model(obs_batch)
                # Compare first action of chunk to target
                loss = F.mse_loss(pred[:, 0, :], act_batch)
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()
                total_loss += loss.item()
                num_batches += 1

            avg_loss = total_loss / max(num_batches, 1)
            final_loss = avg_loss

            # Validation loss
            val_loss: float | None = None
            if has_val:
                model.eval()
                with torch.no_grad():
                    val_pred = model(val_obs_t)
                    val_loss = float(F.mse_loss(val_pred[:, 0, :], val_act_t).item())
                model.train()

            if on_progress:
                on_progress(
                    TrainingProgress(
                        epoch=epoch,
                        total_epochs=cfg.num_epochs,
                        loss=avg_loss,
                        val_loss=val_loss,
                    )
                )

            if epoch % 10 == 0 or epoch == cfg.num_epochs - 1:
                val_str = f", val_loss={val_loss:.6f}" if val_loss is not None else ""
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
                    "architecture": "act",
                    "joint_keys": dataset_info.joint_keys,
                },
            },
            str(ckpt_path),
        )

        logger.info("Checkpoint saved: %s (final_loss=%.6f)", ckpt_path, final_loss)

        return TrainingResult(
            checkpoint_path=ckpt_path,
            final_loss=final_loss,
            epochs_trained=cfg.num_epochs,
        )
