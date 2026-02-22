"""Policy loading and inference for trained checkpoints.

Supports ACT, Diffusion, and PI0.5 (flow matching) architectures. Loads
from ``data/policies/{assembly_id}/{step_id}/policy.pt`` and wraps in a
``Policy``-compatible object with a ``predict()`` API.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import torch

from nextis.learning.trainer import MinimalACT

logger = logging.getLogger(__name__)


class PolicyProtocol(Protocol):
    """Protocol for all policy types — ACT, Diffusion, Flow."""

    @property
    def chunk_size(self) -> int: ...
    @property
    def obs_dim(self) -> int: ...
    @property
    def action_dim(self) -> int: ...
    @property
    def joint_keys(self) -> list[str]: ...
    def predict(self, observation: dict[str, float]) -> np.ndarray: ...


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

    Supports ACT, Diffusion, and PI0.5 (flow matching) architectures.
    Caches loaded models to avoid reloading on every step.

    Args:
        policies_dir: Root directory for policy checkpoints.
    """

    POLICIES_DIR = Path("data/policies")

    def __init__(self, policies_dir: str | Path | None = None) -> None:
        if policies_dir is not None:
            self.POLICIES_DIR = Path(policies_dir)
        self._cache: dict[str, Any] = {}

    def load(self, assembly_id: str, step_id: str) -> Any | None:
        """Load a trained policy for the given assembly step.

        The architecture is read from the checkpoint's config dict and
        the appropriate model class is instantiated.

        Args:
            assembly_id: Assembly identifier.
            step_id: Step identifier.

        Returns:
            Policy-compatible instance, or None if no checkpoint exists.
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
            architecture = config.get("architecture", "act")

            policy = self._load_architecture(architecture, checkpoint, config, ckpt_path)
            if policy is not None:
                self._cache[cache_key] = policy
            return policy

        except Exception as e:
            logger.error("Failed to load policy from %s: %s", ckpt_path, e)
            return None

    def _load_architecture(
        self,
        architecture: str,
        checkpoint: dict,
        config: dict,
        ckpt_path: Path,
    ) -> Any | None:
        """Instantiate the correct model class based on architecture."""
        if architecture == "diffusion":
            return self._load_diffusion(checkpoint, config, ckpt_path)
        if architecture == "pi0":
            return self._load_flow(checkpoint, config, ckpt_path)
        return self._load_act(checkpoint, config, ckpt_path)

    def _load_act(self, checkpoint: dict, config: dict, ckpt_path: Path) -> Policy:
        """Load a MinimalACT policy."""
        model = MinimalACT(
            obs_dim=config["obs_dim"],
            action_dim=config["action_dim"],
            chunk_size=config["chunk_size"],
            hidden_dim=config.get("hidden_dim", 128),
        )
        model.load_state_dict(checkpoint["model_state_dict"])
        model.eval()
        logger.info("Loaded ACT policy: %s", ckpt_path)
        return Policy(model, config)

    def _load_diffusion(self, checkpoint: dict, config: dict, ckpt_path: Path) -> Any | None:
        """Load a DiffusionPolicy and wrap for inference."""
        try:
            from nextis.learning.diffusion_policy import (
                DiffusionInferenceWrapper,
                DiffusionPolicy,
                DiffusionSchedule,
            )

            model = DiffusionPolicy(
                obs_dim=config["obs_dim"],
                action_dim=config["action_dim"],
                chunk_size=config["chunk_size"],
                hidden_dim=config.get("hidden_dim", 256),
                num_diffusion_steps=config.get("num_diffusion_steps", 100),
            )
            model.load_state_dict(checkpoint["model_state_dict"])
            model.eval()

            schedule = DiffusionSchedule(config.get("num_diffusion_steps", 100))
            logger.info("Loaded Diffusion policy: %s", ckpt_path)
            return DiffusionInferenceWrapper(model, config, schedule)
        except ImportError:
            logger.error("Cannot load diffusion policy — missing dependencies")
            return None

    def _load_flow(self, checkpoint: dict, config: dict, ckpt_path: Path) -> Any | None:
        """Load a FlowPolicy and wrap for inference."""
        try:
            from nextis.learning.flow_policy import FlowInferenceWrapper, FlowPolicy

            model = FlowPolicy(
                obs_dim=config["obs_dim"],
                action_dim=config["action_dim"],
                chunk_size=config["chunk_size"],
                hidden_dim=config.get("hidden_dim", 256),
            )
            model.load_state_dict(checkpoint["model_state_dict"])
            model.eval()

            logger.info("Loaded Flow (PI0.5) policy: %s", ckpt_path)
            return FlowInferenceWrapper(model, config)
        except ImportError:
            logger.error("Cannot load flow policy — missing dependencies")
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
