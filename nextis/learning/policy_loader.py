"""Policy loading and inference for trained MinimalACT checkpoints.

Loads a trained policy from ``data/policies/{assembly_id}/{step_id}/policy.pt``
and wraps it in a ``Policy`` object that provides a simple ``predict()`` API.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import torch

from nextis.learning.trainer import MinimalACT

logger = logging.getLogger(__name__)


class Policy:
    """Wraps a loaded MinimalACT model for inference.

    Args:
        model: Trained MinimalACT model (eval mode).
        config: Checkpoint config dict with obs_dim, action_dim, chunk_size.
    """

    def __init__(self, model: MinimalACT, config: dict) -> None:
        self._model = model
        self._config = config

    @property
    def chunk_size(self) -> int:
        """Number of future actions in each prediction."""
        return self._config["chunk_size"]

    @property
    def obs_dim(self) -> int:
        """Expected observation dimensionality."""
        return self._config["obs_dim"]

    @property
    def action_dim(self) -> int:
        """Action dimensionality."""
        return self._config["action_dim"]

    @property
    def joint_keys(self) -> list[str]:
        """Ordered joint key names from training data."""
        return self._config.get("joint_keys", [])

    def predict(self, observation: dict[str, float]) -> np.ndarray:
        """Run inference on a single observation.

        Args:
            observation: Dict mapping joint names to float values. If the
                checkpoint stores ``joint_keys``, those keys are used to
                order the input. Otherwise falls back to
                ``sorted(observation.keys())``.

        Returns:
            Action array of shape ``(chunk_size, action_dim)``.
        """
        keys = self._config.get("joint_keys") or sorted(observation)
        obs_array = np.array([observation[k] for k in keys], dtype=np.float32)
        with torch.no_grad():
            obs_tensor = torch.tensor(obs_array).unsqueeze(0)
            actions = self._model(obs_tensor)
        return actions[0].numpy()  # (chunk_size, action_dim)


class PolicyLoader:
    """Loads trained policy checkpoints from disk.

    Caches loaded models to avoid reloading on every step.

    Args:
        policies_dir: Root directory for policy checkpoints.
    """

    POLICIES_DIR = Path("data/policies")

    def __init__(self, policies_dir: str | Path | None = None) -> None:
        if policies_dir is not None:
            self.POLICIES_DIR = Path(policies_dir)
        self._cache: dict[str, Policy] = {}

    def load(self, assembly_id: str, step_id: str) -> Policy | None:
        """Load a trained policy for the given assembly step.

        Args:
            assembly_id: Assembly identifier.
            step_id: Step identifier.

        Returns:
            Policy instance, or None if no checkpoint exists.
        """
        cache_key = f"{assembly_id}/{step_id}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        ckpt_path = self.POLICIES_DIR / assembly_id / step_id / "policy.pt"
        if not ckpt_path.exists():
            logger.debug("No policy checkpoint at %s", ckpt_path)
            return None

        try:
            checkpoint = torch.load(str(ckpt_path), map_location="cpu", weights_only=True)
            config = checkpoint["config"]

            model = MinimalACT(
                obs_dim=config["obs_dim"],
                action_dim=config["action_dim"],
                chunk_size=config["chunk_size"],
                hidden_dim=config.get("hidden_dim", 128),
            )
            model.load_state_dict(checkpoint["model_state_dict"])
            model.eval()

            policy = Policy(model, config)
            self._cache[cache_key] = policy
            logger.info("Loaded policy: %s", ckpt_path)
            return policy

        except Exception as e:
            logger.error("Failed to load policy from %s: %s", ckpt_path, e)
            return None

    def exists(self, assembly_id: str, step_id: str) -> bool:
        """Check whether a trained checkpoint exists for the given step.

        Args:
            assembly_id: Assembly identifier.
            step_id: Step identifier.

        Returns:
            True if a policy.pt checkpoint file exists on disk.
        """
        ckpt_path = self.POLICIES_DIR / assembly_id / step_id / "policy.pt"
        return ckpt_path.exists()

    def clear_cache(self) -> None:
        """Clear all cached policies."""
        self._cache.clear()
