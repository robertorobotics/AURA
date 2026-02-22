"""Tests for calibration profile I/O and transforms."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nextis.errors import CalibrationError
from nextis.hardware.calibration import CalibrationManager, CalibrationProfile

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

CONFIGS_DIR = Path(__file__).resolve().parent.parent / "configs" / "calibration"


def _make_profile(arm_id: str = "test_arm") -> CalibrationProfile:
    """Build a small profile for testing."""
    return CalibrationProfile(
        arm_id=arm_id,
        zeros={"base": 0.1, "link1": -0.05, "gripper": 0.0},
        ranges={
            "base": {"min": -1.5, "max": 1.5},
            "link1": {"min": -2.0, "max": 2.0},
            "gripper": {"min": -5.0, "max": 0.0},
        },
        inversions={"link1": True, "base": False, "gripper": True},
        gravity={"base": [0.0, -9.81, 0.0], "link1": [0.1, -9.8, 0.0]},
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_round_trip(tmp_path: Path) -> None:
    """Save a profile, reload it, and verify all fields match."""
    original = _make_profile()
    profile_dir = tmp_path / original.arm_id

    original.to_directory(profile_dir)

    loaded = CalibrationProfile.from_directory(profile_dir)

    assert loaded.arm_id == original.arm_id
    assert loaded.zeros == original.zeros
    assert loaded.ranges == original.ranges
    assert loaded.inversions == original.inversions
    assert loaded.gravity == original.gravity


def test_apply_zeros() -> None:
    """apply_zeros subtracts offsets; missing offsets pass through."""
    mgr = CalibrationManager()
    profile = CalibrationProfile(
        arm_id="z",
        zeros={"base": 0.1, "link1": -0.5},
    )
    raw = {"base": 1.0, "link1": 0.5, "link2": 2.0}
    result = mgr.apply_zeros(profile, raw)

    assert result["base"] == pytest.approx(0.9)
    assert result["link1"] == pytest.approx(1.0)
    assert result["link2"] == pytest.approx(2.0)  # no offset -> unchanged


def test_apply_range_clamp() -> None:
    """apply_range_clamp clamps to min/max; unknown joints pass through."""
    mgr = CalibrationManager()
    profile = CalibrationProfile(
        arm_id="r",
        ranges={
            "base": {"min": -1.0, "max": 1.0},
            "link1": {"min": 0.0, "max": 2.0},
        },
    )
    positions = {"base": -5.0, "link1": 3.0, "link2": 99.0}
    result = mgr.apply_range_clamp(profile, positions)

    assert result["base"] == pytest.approx(-1.0)  # clamped up
    assert result["link1"] == pytest.approx(2.0)  # clamped down
    assert result["link2"] == pytest.approx(99.0)  # no range -> pass through


def test_apply_range_clamp_in_range() -> None:
    """Values within range pass through unchanged."""
    mgr = CalibrationManager()
    profile = CalibrationProfile(
        arm_id="r",
        ranges={"base": {"min": -1.0, "max": 1.0}},
    )
    result = mgr.apply_range_clamp(profile, {"base": 0.5})
    assert result["base"] == pytest.approx(0.5)


def test_apply_inversions() -> None:
    """apply_inversions negates flagged joints, leaves others unchanged."""
    mgr = CalibrationManager()
    profile = CalibrationProfile(
        arm_id="i",
        inversions={"link1": True, "base": False},
    )
    positions = {"base": 1.0, "link1": 2.0, "link2": 3.0}
    result = mgr.apply_inversions(profile, positions)

    assert result["base"] == pytest.approx(1.0)  # False -> unchanged
    assert result["link1"] == pytest.approx(-2.0)  # True -> negated
    assert result["link2"] == pytest.approx(3.0)  # not listed -> unchanged


def test_list_calibrated(tmp_path: Path) -> None:
    """list_calibrated returns only dirs with zeros.json."""
    mgr = CalibrationManager(config_dir=tmp_path)

    # arm_a has zeros.json
    arm_a = tmp_path / "arm_a"
    arm_a.mkdir()
    (arm_a / "zeros.json").write_text("{}")

    # arm_b has no zeros.json (just a ranges file)
    arm_b = tmp_path / "arm_b"
    arm_b.mkdir()
    (arm_b / "ranges.json").write_text("{}")

    # arm_c has zeros.json
    arm_c = tmp_path / "arm_c"
    arm_c.mkdir()
    (arm_c / "zeros.json").write_text("{}")

    result = mgr.list_calibrated()
    assert result == ["arm_a", "arm_c"]


def test_load_missing_arm(tmp_path: Path) -> None:
    """Loading a nonexistent arm raises CalibrationError."""
    mgr = CalibrationManager(config_dir=tmp_path)
    with pytest.raises(CalibrationError, match="not found"):
        mgr.load("nonexistent_arm")


def test_load_real_aira_zero() -> None:
    """Load the real aira_zero profile converted from legacy data."""
    if not (CONFIGS_DIR / "aira_zero").exists():
        pytest.skip("aira_zero calibration profile not present")

    mgr = CalibrationManager(config_dir=CONFIGS_DIR)
    profile = mgr.load("aira_zero")

    assert profile.arm_id == "aira_zero"
    assert len(profile.zeros) == 7
    assert len(profile.ranges) == 7
    assert len(profile.inversions) == 3
    assert profile.inversions.get("link1") is True
    assert profile.inversions.get("link3") is True
    assert profile.inversions.get("gripper") is True
    assert profile.gravity is None


def test_load_real_aira_zero_leader() -> None:
    """Load the real aira_zero_leader profile converted from legacy data."""
    if not (CONFIGS_DIR / "aira_zero_leader").exists():
        pytest.skip("aira_zero_leader calibration profile not present")

    mgr = CalibrationManager(config_dir=CONFIGS_DIR)
    profile = mgr.load("aira_zero_leader")

    assert profile.arm_id == "aira_zero_leader"
    assert len(profile.zeros) == 7
    assert len(profile.ranges) == 7
    # aira_zero_leader has non-zero homing offsets
    assert profile.zeros["joint_1"] == -6
    assert profile.zeros["joint_2"] == 1097


def test_legacy_format_loading(tmp_path: Path) -> None:
    """from_directory can load a legacy monolithic motor calibration file."""
    arm_dir = tmp_path / "legacy_arm"
    arm_dir.mkdir()

    legacy_data = {
        "base": {
            "id": 1,
            "drive_mode": 0,
            "homing_offset": 0.5,
            "range_min": -1.0,
            "range_max": 1.0,
        },
        "link1": {
            "id": 2,
            "drive_mode": 0,
            "homing_offset": -0.3,
            "range_min": -2.0,
            "range_max": 2.0,
        },
    }
    (arm_dir / "cal_profile.json").write_text(json.dumps(legacy_data))
    (arm_dir / "inversions.json").write_text(json.dumps({"link1": True}))

    profile = CalibrationProfile.from_directory(arm_dir)

    assert profile.arm_id == "legacy_arm"
    assert profile.zeros == {"base": 0.5, "link1": -0.3}
    assert profile.ranges["base"] == {"min": -1.0, "max": 1.0}
    assert profile.ranges["link1"] == {"min": -2.0, "max": 2.0}
    assert profile.inversions == {"link1": True}
    assert profile.gravity is None


# ---------------------------------------------------------------------------
# Interactive method tests
# ---------------------------------------------------------------------------


def test_record_zeros(tmp_path: Path) -> None:
    """record_zeros creates a profile with zero offsets and saves to disk."""
    mgr = CalibrationManager(config_dir=tmp_path)
    positions = {"base": 0.5, "link1": -0.3, "gripper": 0.1}
    profile = mgr.record_zeros("test_arm", positions)

    assert profile.zeros == positions
    assert (tmp_path / "test_arm" / "zeros.json").exists()

    # Reload and verify
    loaded = mgr.load("test_arm")
    assert loaded.zeros == positions


def test_record_zeros_preserves_existing(tmp_path: Path) -> None:
    """record_zeros preserves ranges/inversions from an existing profile."""
    mgr = CalibrationManager(config_dir=tmp_path)
    existing = CalibrationProfile(
        arm_id="test_arm",
        zeros={"base": 0.0},
        ranges={"base": {"min": -1.0, "max": 1.0}},
        inversions={"link1": True},
    )
    mgr.save(existing)

    new_zeros = {"base": 0.5, "link1": -0.3}
    profile = mgr.record_zeros("test_arm", new_zeros)

    assert profile.zeros == new_zeros
    assert profile.ranges == {"base": {"min": -1.0, "max": 1.0}}
    assert profile.inversions == {"link1": True}


def test_get_status_no_profile(tmp_path: Path) -> None:
    """get_status reports all False when no profile exists."""
    mgr = CalibrationManager(config_dir=tmp_path)
    status = mgr.get_status("test_arm")

    assert status["arm_id"] == "test_arm"
    assert not status["has_zeros"]
    assert not status["has_ranges"]
    assert not status["has_inversions"]
    assert not status["has_gravity"]


def test_get_status_partial(tmp_path: Path) -> None:
    """get_status correctly detects individual files."""
    mgr = CalibrationManager(config_dir=tmp_path)
    arm_dir = tmp_path / "test_arm"
    arm_dir.mkdir()
    (arm_dir / "zeros.json").write_text("{}")

    status = mgr.get_status("test_arm")
    assert status["has_zeros"]
    assert not status["has_ranges"]


def test_delete_profile(tmp_path: Path) -> None:
    """delete_profile removes the entire arm directory."""
    mgr = CalibrationManager(config_dir=tmp_path)
    profile = _make_profile()
    mgr.save(profile)
    assert (tmp_path / "test_arm").exists()

    mgr.delete_profile("test_arm")
    assert not (tmp_path / "test_arm").exists()


def test_delete_nonexistent_raises(tmp_path: Path) -> None:
    """delete_profile raises CalibrationError for a missing arm."""
    mgr = CalibrationManager(config_dir=tmp_path)
    with pytest.raises(CalibrationError):
        mgr.delete_profile("nonexistent")
