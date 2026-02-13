"""HDF5 demo → numpy dataset builder for per-step policy training.

Merges all HDF5 demonstration files for a given assembly step into
train/val numpy arrays suitable for the PolicyTrainer.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from nextis.errors import TrainingError

logger = logging.getLogger(__name__)

try:
    import h5py
except ImportError:
    h5py = None  # type: ignore[assignment]


@dataclass
class DatasetInfo:
    """Metadata about a built training dataset.

    Attributes:
        assembly_id: Assembly this dataset belongs to.
        step_id: Step this dataset trains a policy for.
        output_dir: Directory containing the .npy files.
        train_frames: Number of training frames.
        val_frames: Number of validation frames.
        obs_dim: Observation dimensionality (number of joints).
        action_dim: Action dimensionality (number of joints).
        joint_keys: Ordered joint names from the HDF5 observation group.
    """

    assembly_id: str
    step_id: str
    output_dir: Path
    train_frames: int
    val_frames: int
    obs_dim: int
    action_dim: int
    joint_keys: list[str] = field(default_factory=list)


class StepDataset:
    """Builds a training dataset from recorded HDF5 demonstrations.

    Args:
        assembly_id: Assembly identifier.
        step_id: Step identifier.
        data_dir: Root data directory (default ``"data"``).
    """

    def __init__(self, assembly_id: str, step_id: str, data_dir: str = "data") -> None:
        self._assembly_id = assembly_id
        self._step_id = step_id
        self._data_dir = Path(data_dir)
        self._demo_dir = self._data_dir / "demos" / assembly_id / step_id
        self._datasets_dir = self._data_dir / "datasets"

    def build(self) -> DatasetInfo:
        """Merge HDF5 demos into train/val numpy arrays.

        Reads ``observation/joint_positions`` and ``action/joint_positions``
        from each demo file, concatenates, splits 80/20, and saves to
        ``data/datasets/{assembly_id}/{step_id}/``.

        Returns:
            DatasetInfo with paths and dimensions.

        Raises:
            TrainingError: If no demos exist or h5py is unavailable.
        """
        if h5py is None:
            raise TrainingError("h5py is required for dataset building but not installed")

        demo_files = sorted(self._demo_dir.glob("*.hdf5"))
        if not demo_files:
            raise TrainingError(
                f"No demos found for {self._assembly_id}/{self._step_id} in {self._demo_dir}"
            )

        all_obs: list[np.ndarray] = []
        all_actions: list[np.ndarray] = []
        joint_keys: list[str] = []

        for fpath in demo_files:
            try:
                with h5py.File(str(fpath), "r") as hf:
                    obs = hf["observation/joint_positions"][:]
                    act = hf["action/joint_positions"][:]
                    all_obs.append(obs)
                    all_actions.append(act)
                    if not joint_keys and "joint_keys" in hf["observation"].attrs:
                        joint_keys = [str(k) for k in hf["observation"].attrs["joint_keys"]]
                    logger.debug("Loaded %s: %d frames", fpath.name, len(obs))
            except Exception as e:
                logger.warning("Skipping corrupt demo %s: %s", fpath.name, e)
                continue

        if not all_obs:
            raise TrainingError(
                f"All demo files for {self._assembly_id}/{self._step_id} were unreadable"
            )

        obs = np.concatenate(all_obs, axis=0)
        actions = np.concatenate(all_actions, axis=0)

        # Align lengths (in case obs and actions differ)
        n = min(len(obs), len(actions))
        obs = obs[:n]
        actions = actions[:n]

        if not joint_keys:
            joint_keys = [f"joint_{i}" for i in range(obs.shape[1])]
            logger.warning(
                "No joint_keys in demos for %s/%s — using synthetic keys",
                self._assembly_id,
                self._step_id,
            )

        # 80/20 train/val split
        split = int(n * 0.8)
        if split == 0:
            split = 1  # At least one training frame

        output_dir = self._datasets_dir / self._assembly_id / self._step_id
        output_dir.mkdir(parents=True, exist_ok=True)

        np.save(output_dir / "train_obs.npy", obs[:split])
        np.save(output_dir / "train_act.npy", actions[:split])
        np.save(output_dir / "val_obs.npy", obs[split:])
        np.save(output_dir / "val_act.npy", actions[split:])

        info = DatasetInfo(
            assembly_id=self._assembly_id,
            step_id=self._step_id,
            output_dir=output_dir,
            train_frames=split,
            val_frames=n - split,
            obs_dim=obs.shape[1],
            action_dim=actions.shape[1],
            joint_keys=joint_keys,
        )

        logger.info(
            "Dataset built: %s/%s — %d train, %d val (obs=%d, act=%d)",
            self._assembly_id,
            self._step_id,
            info.train_frames,
            info.val_frames,
            info.obs_dim,
            info.action_dim,
        )

        return info
