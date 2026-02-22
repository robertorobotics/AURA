"""Dataset service — CRUD operations for recorded HDF5 demonstrations.

Provides listing, inspection, validation, and deletion of per-step
demonstration files stored under ``data/demos/{assembly_id}/{step_id}/``.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

try:
    import h5py
except ImportError:
    h5py = None  # type: ignore[assignment]


class DatasetService:
    """Manages recorded demonstration datasets.

    Args:
        demos_dir: Root demos directory (``data/demos``).
    """

    def __init__(self, demos_dir: Path) -> None:
        self._demos_dir = demos_dir

    def _step_dir(self, assembly_id: str, step_id: str) -> Path:
        return self._demos_dir / assembly_id / step_id

    def _demo_path(self, assembly_id: str, step_id: str, demo_id: str) -> Path:
        return self._step_dir(assembly_id, step_id) / f"{demo_id}.hdf5"

    def list_demos(self, assembly_id: str, step_id: str) -> list[dict]:
        """List all demo HDF5 files for a step with metadata.

        Returns:
            List of dicts with demo_id, num_frames, duration_s, timestamp,
            has_images, and file_size_bytes, sorted by timestamp.
        """
        step_dir = self._step_dir(assembly_id, step_id)
        if not step_dir.exists():
            return []

        demos: list[dict] = []
        for fpath in sorted(step_dir.glob("*.hdf5")):
            info = self._read_demo_attrs(fpath)
            if info is not None:
                demos.append(info)

        demos.sort(key=lambda d: d["timestamp"])
        return demos

    def get_demo_info(self, assembly_id: str, step_id: str, demo_id: str) -> dict | None:
        """Get detailed info for a single demo.

        Returns:
            Dict with metadata, or None if not found.
        """
        fpath = self._demo_path(assembly_id, step_id, demo_id)
        if not fpath.exists():
            return None
        return self._read_demo_attrs(fpath)

    def validate_demo(self, assembly_id: str, step_id: str, demo_id: str) -> dict:
        """Check HDF5 integrity for a single demo.

        Returns:
            Dict with ``valid`` (bool) and ``errors`` (list of strings).
        """
        fpath = self._demo_path(assembly_id, step_id, demo_id)
        errors: list[str] = []

        if not fpath.exists():
            return {"valid": False, "errors": [f"File not found: {fpath.name}"]}

        if h5py is None:
            return {"valid": False, "errors": ["h5py not installed"]}

        try:
            with h5py.File(str(fpath), "r") as hf:
                # Required datasets
                if "observation/joint_positions" not in hf:
                    errors.append("Missing observation/joint_positions")
                if "action/joint_positions" not in hf:
                    errors.append("Missing action/joint_positions")

                # Shape consistency
                if not errors:
                    obs = hf["observation/joint_positions"]
                    act = hf["action/joint_positions"]
                    if obs.shape[0] != act.shape[0]:
                        errors.append(
                            f"Shape mismatch: obs has {obs.shape[0]} frames, "
                            f"action has {act.shape[0]}"
                        )
                    if obs.shape[0] == 0:
                        errors.append("Empty dataset (0 frames)")

                    # Check for NaN
                    obs_data = obs[:]
                    if np.any(np.isnan(obs_data)):
                        errors.append("NaN values in observation/joint_positions")
                    act_data = act[:]
                    if np.any(np.isnan(act_data)):
                        errors.append("NaN values in action/joint_positions")

                # Timestamps
                if "timestamps" in hf:
                    ts = hf["timestamps"][:]
                    if len(ts) > 1 and not np.all(np.diff(ts) >= 0):
                        errors.append("Timestamps are not monotonically increasing")

        except Exception as e:
            errors.append(f"Failed to open HDF5: {e}")

        return {"valid": len(errors) == 0, "errors": errors}

    def validate_all(self, assembly_id: str, step_id: str) -> dict:
        """Validate all demos for a step.

        Returns:
            Dict with ``total``, ``valid``, ``invalid``, and per-demo ``results``.
        """
        demos = self.list_demos(assembly_id, step_id)
        results: list[dict] = []
        valid_count = 0

        for demo in demos:
            result = self.validate_demo(assembly_id, step_id, demo["demo_id"])
            result["demo_id"] = demo["demo_id"]
            results.append(result)
            if result["valid"]:
                valid_count += 1

        return {
            "total": len(demos),
            "valid": valid_count,
            "invalid": len(demos) - valid_count,
            "results": results,
        }

    def delete_demo(self, assembly_id: str, step_id: str, demo_id: str) -> bool:
        """Delete a single demo file.

        Returns:
            True if deleted, False if not found.
        """
        fpath = self._demo_path(assembly_id, step_id, demo_id)
        if not fpath.exists():
            return False
        fpath.unlink()
        logger.info("Deleted demo: %s", fpath)
        return True

    def get_summary(self, assembly_id: str, step_id: str) -> dict:
        """Summary: demo count, total frames across all demos.

        Returns:
            Dict with assembly_id, step_id, demo_count, total_frames, demos.
        """
        demos = self.list_demos(assembly_id, step_id)
        total_frames = sum(d["num_frames"] for d in demos)
        return {
            "assembly_id": assembly_id,
            "step_id": step_id,
            "demo_count": len(demos),
            "total_frames": total_frames,
            "demos": demos,
        }

    def _read_demo_attrs(self, fpath: Path) -> dict | None:
        """Read metadata from a single HDF5 demo file."""
        if h5py is None:
            logger.warning("h5py not installed — cannot read demo metadata")
            return None

        try:
            with h5py.File(str(fpath), "r") as hf:
                num_frames = int(hf.attrs.get("num_frames", 0))
                recording_hz = int(hf.attrs.get("recording_hz", 50))
                timestamp = float(hf.attrs.get("timestamp", fpath.stat().st_mtime))
                duration_s = num_frames / recording_hz if recording_hz > 0 else 0.0
                has_images = "observation/images" in hf

            return {
                "demo_id": fpath.stem,
                "num_frames": num_frames,
                "duration_s": round(duration_s, 2),
                "has_images": has_images,
                "timestamp": timestamp,
                "file_size_bytes": fpath.stat().st_size,
            }
        except Exception as e:
            logger.warning("Cannot read demo %s: %s", fpath.name, e)
            return None
