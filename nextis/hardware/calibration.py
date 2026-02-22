"""Calibration profile I/O and pure-function transforms.

Loads, saves, and applies calibration profiles for AURA arms. Supports both
the new AURA split-file format (zeros.json, ranges.json, inversions.json,
gravity.json) and the legacy Nextis_Bridge monolithic format for backward
compatibility.

Interactive calibration routines (zero recording, range discovery) are NOT
included here -- those require hardware and a human operator.
"""

from __future__ import annotations

import json
import logging
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nextis.errors import CalibrationError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Joint name translation maps (Dynamixel leader <-> Damiao follower)
# ---------------------------------------------------------------------------

DYNAMIXEL_TO_DAMIAO: dict[str, str] = {
    "joint_1": "base",
    "joint_2": "link1",
    "joint_3": "link2",
    "joint_4": "link3",
    "joint_5": "link4",
    "joint_6": "link5",
    "gripper": "gripper",
}

DAMIAO_TO_DYNAMIXEL: dict[str, str] = {v: k for k, v in DYNAMIXEL_TO_DAMIAO.items()}

# Files that are not legacy calibration profiles (skipped during auto-detection)
_NON_PROFILE_FILES = {"inversions.json", "active_profiles.json", "gravity.json"}

# Required keys in a legacy motor entry to identify the format
_LEGACY_MOTOR_KEYS = {"id", "homing_offset", "range_min", "range_max"}


# ---------------------------------------------------------------------------
# CalibrationProfile
# ---------------------------------------------------------------------------


@dataclass
class CalibrationProfile:
    """Calibration data for a single arm.

    Attributes:
        arm_id: Unique arm identifier (e.g., "aira_zero").
        zeros: Per-joint zero offsets subtracted from raw encoder readings.
        ranges: Per-joint min/max limits. Each value is ``{"min": float, "max": float}``.
        inversions: Per-joint sign-flip flags. ``True`` means negate the value.
        gravity: Optional per-joint gravity compensation vectors. ``None`` if not recorded.
    """

    arm_id: str
    zeros: dict[str, float] = field(default_factory=dict)
    ranges: dict[str, dict[str, float]] = field(default_factory=dict)
    inversions: dict[str, bool] = field(default_factory=dict)
    gravity: dict[str, list[float]] | None = None

    # -- Persistence (new AURA split-file format) --

    def to_directory(self, path: Path) -> None:
        """Write profile as separate JSON files into *path*.

        Creates the directory if it does not exist. Writes ``zeros.json``,
        ``ranges.json``, ``inversions.json``, and optionally ``gravity.json``.

        Args:
            path: Target directory (e.g., ``configs/calibration/aira_zero``).
        """
        path.mkdir(parents=True, exist_ok=True)

        _write_json(path / "zeros.json", self.zeros)
        _write_json(path / "ranges.json", self.ranges)
        _write_json(path / "inversions.json", self.inversions)

        if self.gravity is not None:
            _write_json(path / "gravity.json", self.gravity)

        logger.info("Saved calibration profile for '%s' to %s", self.arm_id, path)

    @classmethod
    def from_directory(cls, path: Path) -> CalibrationProfile:
        """Load a calibration profile from a directory.

        Supports two formats:
        1. **AURA format** -- detected by the presence of ``zeros.json``. Reads
           ``zeros.json``, ``ranges.json``, ``inversions.json``, and optionally
           ``gravity.json``.
        2. **Legacy Nextis_Bridge format** -- monolithic per-motor JSON files
           where each entry has ``id``, ``homing_offset``, ``range_min``,
           ``range_max``. The first valid profile file found is used.

        Args:
            path: Directory containing calibration files.

        Returns:
            Populated ``CalibrationProfile``.

        Raises:
            CalibrationError: If the directory does not exist or contains no
                recognizable calibration data.
        """
        if not path.is_dir():
            raise CalibrationError(f"Calibration directory not found: {path}")

        arm_id = path.name

        # -- Try AURA format first --
        zeros_path = path / "zeros.json"
        if zeros_path.exists():
            return cls._load_aura_format(path, arm_id)

        # -- Fall back to legacy format --
        return cls._load_legacy_format(path, arm_id)

    # -- Private loaders --

    @classmethod
    def _load_aura_format(cls, path: Path, arm_id: str) -> CalibrationProfile:
        """Load from AURA split-file format."""
        zeros = _read_json(path / "zeros.json")
        ranges = _read_json(path / "ranges.json")

        inversions_path = path / "inversions.json"
        inversions = _read_json(inversions_path) if inversions_path.exists() else {}

        gravity_path = path / "gravity.json"
        gravity = _read_json(gravity_path) if gravity_path.exists() else None

        logger.info(
            "Loaded AURA calibration for '%s': %d joints, %d inversions",
            arm_id,
            len(zeros),
            sum(1 for v in inversions.values() if v),
        )
        return cls(
            arm_id=arm_id,
            zeros=zeros,
            ranges=ranges,
            inversions=inversions,
            gravity=gravity,
        )

    @classmethod
    def _load_legacy_format(cls, path: Path, arm_id: str) -> CalibrationProfile:
        """Load from legacy Nextis_Bridge monolithic per-motor JSON.

        Legacy format stores all motor calibration in a single file:
        ``{"base": {"id": 1, "homing_offset": 0, "range_min": -1.5, "range_max": 1.5}, ...}``

        This method extracts zeros (homing_offset), ranges (range_min/range_max),
        and inversions (from a separate inversions.json if present).
        """
        profile_path = _find_legacy_profile(path)
        if profile_path is None:
            raise CalibrationError(
                f"No calibration data found in {path} "
                "(expected zeros.json or a legacy motor calibration file)"
            )

        data = _read_json(profile_path)
        zeros: dict[str, float] = {}
        ranges: dict[str, dict[str, float]] = {}

        for joint_name, entry in data.items():
            if not isinstance(entry, dict) or not _LEGACY_MOTOR_KEYS.issubset(entry):
                continue
            zeros[joint_name] = entry["homing_offset"]
            ranges[joint_name] = {"min": entry["range_min"], "max": entry["range_max"]}

        # Inversions stored separately in legacy format too
        inversions_path = path / "inversions.json"
        inversions = _read_json(inversions_path) if inversions_path.exists() else {}

        logger.info(
            "Loaded legacy calibration for '%s' from %s: %d joints, %d inversions",
            arm_id,
            profile_path.name,
            len(zeros),
            sum(1 for v in inversions.values() if v),
        )
        return cls(
            arm_id=arm_id,
            zeros=zeros,
            ranges=ranges,
            inversions=inversions,
            gravity=None,
        )


# ---------------------------------------------------------------------------
# CalibrationManager
# ---------------------------------------------------------------------------


class CalibrationManager:
    """Manages calibration profiles on disk.

    Provides load/save operations and pure-function transforms (apply_zeros,
    apply_range_clamp, apply_inversions) that do not require hardware.

    Args:
        config_dir: Root directory for calibration profiles.
    """

    def __init__(self, config_dir: Path = Path("configs/calibration")) -> None:
        self._config_dir = config_dir

    def load(self, arm_id: str) -> CalibrationProfile:
        """Load a calibration profile for the given arm.

        Args:
            arm_id: Arm identifier (subdirectory name under config_dir).

        Returns:
            Loaded ``CalibrationProfile``.

        Raises:
            CalibrationError: If the arm directory or calibration data is missing.
        """
        arm_dir = self._config_dir / arm_id
        return CalibrationProfile.from_directory(arm_dir)

    def save(self, profile: CalibrationProfile) -> Path:
        """Save a calibration profile to disk.

        Args:
            profile: Profile to persist.

        Returns:
            Path to the arm's calibration directory.
        """
        arm_dir = self._config_dir / profile.arm_id
        profile.to_directory(arm_dir)
        return arm_dir

    def list_calibrated(self) -> list[str]:
        """Return arm IDs that have calibration data.

        Only directories containing ``zeros.json`` are considered calibrated.

        Returns:
            Sorted list of arm ID strings.
        """
        if not self._config_dir.is_dir():
            return []
        result = []
        for child in sorted(self._config_dir.iterdir()):
            if child.is_dir() and (child / "zeros.json").exists():
                result.append(child.name)
        return result

    def apply_zeros(
        self, profile: CalibrationProfile, raw_positions: dict[str, float]
    ) -> dict[str, float]:
        """Subtract zero offsets from raw encoder readings.

        Joints not present in ``profile.zeros`` pass through unchanged.

        Args:
            profile: Calibration profile with zero offsets.
            raw_positions: Raw joint positions keyed by joint name.

        Returns:
            Corrected positions.
        """
        return {k: v - profile.zeros.get(k, 0.0) for k, v in raw_positions.items()}

    def apply_range_clamp(
        self, profile: CalibrationProfile, positions: dict[str, float]
    ) -> dict[str, float]:
        """Clamp positions to calibrated min/max ranges.

        Joints not present in ``profile.ranges`` pass through unchanged.

        Args:
            profile: Calibration profile with range limits.
            positions: Joint positions keyed by joint name.

        Returns:
            Clamped positions.
        """
        result: dict[str, float] = {}
        for joint, value in positions.items():
            limits = profile.ranges.get(joint)
            if limits is not None:
                result[joint] = max(limits["min"], min(limits["max"], value))
            else:
                result[joint] = value
        return result

    def apply_inversions(
        self, profile: CalibrationProfile, positions: dict[str, float]
    ) -> dict[str, float]:
        """Flip sign on joints marked as inverted.

        Joints not listed in ``profile.inversions`` or marked ``False`` pass
        through unchanged.

        Args:
            profile: Calibration profile with inversion flags.
            positions: Joint positions keyed by joint name.

        Returns:
            Positions with inverted joints negated.
        """
        return {k: -v if profile.inversions.get(k, False) else v for k, v in positions.items()}

    # -- Interactive calibration --

    def record_zeros(self, arm_id: str, positions: dict[str, float]) -> CalibrationProfile:
        """Record current joint positions as zero offsets and save.

        Preserves existing ranges/inversions/gravity if a profile already exists.

        Args:
            arm_id: Arm identifier.
            positions: Current raw joint positions to use as zeros.

        Returns:
            Updated ``CalibrationProfile``.
        """
        try:
            profile = self.load(arm_id)
        except CalibrationError:
            profile = CalibrationProfile(arm_id=arm_id)
        profile.zeros = dict(positions)
        self.save(profile)
        return profile

    def get_status(self, arm_id: str) -> dict[str, Any]:
        """Check which calibration files exist for an arm.

        Args:
            arm_id: Arm identifier.

        Returns:
            Dict with ``arm_id``, ``has_zeros``, ``has_ranges``,
            ``has_inversions``, ``has_gravity``.
        """
        arm_dir = self._config_dir / arm_id
        return {
            "arm_id": arm_id,
            "has_zeros": (arm_dir / "zeros.json").is_file(),
            "has_ranges": (arm_dir / "ranges.json").is_file(),
            "has_inversions": (arm_dir / "inversions.json").is_file(),
            "has_gravity": (arm_dir / "gravity.json").is_file(),
        }

    def delete_profile(self, arm_id: str) -> None:
        """Remove all calibration data for an arm.

        Args:
            arm_id: Arm identifier.

        Raises:
            CalibrationError: If no profile directory exists.
        """
        arm_dir = self._config_dir / arm_id
        if not arm_dir.is_dir():
            raise CalibrationError(f"No calibration profile for '{arm_id}'")
        shutil.rmtree(arm_dir)
        logger.info("Deleted calibration profile for '%s'", arm_id)

    def start_range_discovery(
        self,
        arm_id: str,
        robot_instance: Any,
        speed: float = 0.1,
        duration_per_joint: float = 10.0,
        joints: list[str] | None = None,
    ) -> None:
        """Start passive range discovery in a background thread.

        The user physically moves the arm through its range of motion while
        positions are recorded at 10 Hz. Min/max per joint are saved as the
        ranges profile.

        Args:
            arm_id: Arm identifier.
            robot_instance: Connected robot instance (must support ``get_observation``).
            speed: Unused — kept for API compatibility.
            duration_per_joint: Seconds to record per joint (or total if discovering all).
            joints: Specific joints to discover, or ``None`` for all.

        Raises:
            CalibrationError: If discovery is already running for this arm.
        """
        with _range_discovery_lock:
            existing = _range_discovery_state.get(arm_id)
            if existing and existing.get("phase") == "running":
                raise CalibrationError(f"Range discovery already running for '{arm_id}'")
            _range_discovery_state[arm_id] = {
                "phase": "running",
                "progress": 0.0,
                "current_joint": None,
                "error": None,
            }

        thread = threading.Thread(
            target=self._range_discovery_loop,
            args=(arm_id, robot_instance, duration_per_joint, joints),
            daemon=True,
            name=f"RangeDiscovery-{arm_id}",
        )
        thread.start()

    def get_range_discovery_status(self, arm_id: str) -> dict | None:
        """Return range discovery progress for an arm, or ``None`` if idle."""
        return _range_discovery_state.get(arm_id)

    def _range_discovery_loop(
        self,
        arm_id: str,
        robot_instance: Any,
        duration_per_joint: float,
        joints: list[str] | None,
    ) -> None:
        """Background loop: read positions at 10 Hz and record min/max."""
        try:
            # Determine joint names from a single observation
            obs = robot_instance.get_observation()
            all_joints = [k for k in obs if k.endswith(".pos") or "position" in k.lower()]
            if not all_joints:
                # Try direct motor names
                all_joints = list(getattr(robot_instance, "motor_names", []))
            if not all_joints:
                raise CalibrationError("Could not determine joint names from robot")

            target_joints = joints if joints else all_joints
            mins: dict[str, float] = {}
            maxs: dict[str, float] = {}

            for i, joint in enumerate(target_joints):
                with _range_discovery_lock:
                    _range_discovery_state[arm_id].update(
                        {
                            "progress": i / len(target_joints),
                            "current_joint": joint,
                        }
                    )

                samples = int(duration_per_joint * 10)
                for _ in range(samples):
                    try:
                        obs = robot_instance.get_observation()
                        val = obs.get(joint)
                        if val is not None:
                            fval = float(val)
                            mins[joint] = min(mins.get(joint, fval), fval)
                            maxs[joint] = max(maxs.get(joint, fval), fval)
                    except Exception:
                        pass
                    time.sleep(0.1)

            # Build and save ranges
            ranges: dict[str, dict[str, float]] = {}
            for joint in target_joints:
                if joint in mins and joint in maxs:
                    ranges[joint] = {"min": mins[joint], "max": maxs[joint]}

            try:
                profile = self.load(arm_id)
            except CalibrationError:
                profile = CalibrationProfile(arm_id=arm_id)
            profile.ranges = ranges
            self.save(profile)

            with _range_discovery_lock:
                _range_discovery_state[arm_id] = {
                    "phase": "complete",
                    "progress": 1.0,
                    "current_joint": None,
                    "error": None,
                }
            logger.info("Range discovery complete for '%s': %d joints", arm_id, len(ranges))

        except Exception as exc:
            logger.error("Range discovery failed for '%s': %s", arm_id, exc)
            with _range_discovery_lock:
                _range_discovery_state[arm_id] = {
                    "phase": "error",
                    "progress": 0.0,
                    "current_joint": None,
                    "error": str(exc),
                }


# ---------------------------------------------------------------------------
# Range discovery background state
# ---------------------------------------------------------------------------

_range_discovery_state: dict[str, dict] = {}
_range_discovery_lock = threading.Lock()


# ---------------------------------------------------------------------------
# File I/O helpers
# ---------------------------------------------------------------------------


def _read_json(path: Path) -> Any:
    """Read and parse a JSON file."""
    with open(path) as f:
        return json.load(f)


def _write_json(path: Path, data: Any) -> None:
    """Write data as formatted JSON."""
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def _find_legacy_profile(directory: Path) -> Path | None:
    """Find the first legacy motor calibration file in a directory.

    Skips known non-profile files (inversions.json, active_profiles.json).
    Returns ``None`` if no valid legacy profile is found.
    """
    for candidate in sorted(directory.glob("*.json")):
        if candidate.name in _NON_PROFILE_FILES:
            continue
        try:
            data = _read_json(candidate)
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        # Check if at least one entry looks like a legacy motor calibration
        for entry in data.values():
            if isinstance(entry, dict) and _LEGACY_MOTOR_KEYS.issubset(entry):
                return candidate
    return None
