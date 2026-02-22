"""Calibration routes — profile management and interactive calibration.

Manages calibration profiles (zeros, ranges, inversions, gravity) for each
arm. Range discovery runs in a background thread with progress polling.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from nextis.api.schemas import (
    CalibrationProfileResponse,
    CalibrationStatusResponse,
    RangeDiscoveryRequest,
)
from nextis.errors import CalibrationError
from nextis.hardware.types import ConnectionStatus

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_managers() -> tuple[Any, Any]:
    """Return (CalibrationManager, ArmRegistryService) from SystemState."""
    from nextis.state import get_state

    state = get_state()
    return state.calibration_manager, state.arm_registry


def _read_positions(instance: Any) -> dict[str, float]:
    """Read current motor positions from a robot instance.

    Uses the same pattern as ``ArmRegistryService.set_home()``.
    """
    positions: dict[str, float] = {}
    if hasattr(instance, "get_observation"):
        obs = instance.get_observation()
        for key, val in obs.items():
            if key.endswith(".pos") or "position" in key.lower():
                positions[key] = float(val)
    elif hasattr(instance, "bus") and hasattr(instance.bus, "read"):
        motor_names = getattr(instance, "motor_names", [])
        for name in motor_names:
            try:
                val = instance.bus.read("Present_Position", name)
                if val is not None:
                    positions[name] = float(val)
            except Exception:
                pass
    return positions


@router.get("/{arm_id}/status", response_model=CalibrationStatusResponse)
async def calibration_status(arm_id: str) -> CalibrationStatusResponse:
    """Return calibration profile status for an arm."""
    cal_mgr, reg = _get_managers()
    if arm_id not in reg.arms:
        raise HTTPException(404, f"Arm '{arm_id}' not found")

    file_status = cal_mgr.get_status(arm_id)
    discovery = cal_mgr.get_range_discovery_status(arm_id)

    return CalibrationStatusResponse(
        arm_id=arm_id,
        has_zeros=file_status["has_zeros"],
        has_ranges=file_status["has_ranges"],
        has_inversions=file_status["has_inversions"],
        has_gravity=file_status["has_gravity"],
        range_discovery_active=(discovery is not None and discovery.get("phase") == "running"),
        range_discovery_progress=(discovery.get("progress", 0.0) if discovery else 0.0),
        range_discovery_joint=(discovery.get("current_joint") if discovery else None),
    )


@router.post("/{arm_id}/zero")
def record_zeros(arm_id: str) -> dict:
    """Record current joint positions as zero offsets."""
    cal_mgr, reg = _get_managers()
    arm = reg.arms.get(arm_id)
    if arm is None:
        raise HTTPException(404, f"Arm '{arm_id}' not found")
    if reg.arm_status.get(arm_id) != ConnectionStatus.CONNECTED:
        raise HTTPException(400, f"Arm '{arm_id}' must be connected to record zeros")

    instance = reg.get_arm_instance(arm_id)
    if instance is None:
        raise HTTPException(500, "Arm instance not available")

    positions = _read_positions(instance)
    if not positions:
        raise HTTPException(500, "Could not read motor positions")

    profile = cal_mgr.record_zeros(arm_id, positions)
    reg.set_arm_calibrated(arm_id, True)
    logger.info("Recorded zeros for %s: %d joints", arm_id, len(profile.zeros))
    return {"status": "ok", "armId": arm_id, "joints": len(profile.zeros)}


@router.post("/{arm_id}/range")
def start_range_discovery(arm_id: str, request: RangeDiscoveryRequest | None = None) -> dict:
    """Start passive range discovery in a background thread."""
    cal_mgr, reg = _get_managers()
    arm = reg.arms.get(arm_id)
    if arm is None:
        raise HTTPException(404, f"Arm '{arm_id}' not found")
    if reg.arm_status.get(arm_id) != ConnectionStatus.CONNECTED:
        raise HTTPException(400, f"Arm '{arm_id}' must be connected for range discovery")

    instance = reg.get_arm_instance(arm_id)
    if instance is None:
        raise HTTPException(500, "Arm instance not available")

    speed = request.speed if request else 0.1
    duration = request.duration_per_joint if request else 10.0
    joints = request.joints if request else None

    try:
        cal_mgr.start_range_discovery(
            arm_id,
            instance,
            speed=speed,
            duration_per_joint=duration,
            joints=joints,
        )
    except CalibrationError as exc:
        raise HTTPException(409, str(exc)) from None

    return {"status": "ok", "armId": arm_id}


@router.post("/{arm_id}/apply")
def apply_calibration(arm_id: str) -> dict:
    """Apply saved calibration profile to arm (marks as calibrated)."""
    cal_mgr, reg = _get_managers()
    if arm_id not in reg.arms:
        raise HTTPException(404, f"Arm '{arm_id}' not found")

    try:
        profile = cal_mgr.load(arm_id)
    except CalibrationError as exc:
        raise HTTPException(404, str(exc)) from None

    reg.set_arm_calibrated(arm_id, True)
    logger.info("Applied calibration for %s", arm_id)
    return {"status": "ok", "armId": arm_id, "joints": len(profile.zeros)}


@router.get("/{arm_id}/profile", response_model=CalibrationProfileResponse)
async def get_profile(arm_id: str) -> CalibrationProfileResponse:
    """Return the full calibration profile data."""
    cal_mgr, reg = _get_managers()
    if arm_id not in reg.arms:
        raise HTTPException(404, f"Arm '{arm_id}' not found")

    try:
        profile = cal_mgr.load(arm_id)
    except CalibrationError as exc:
        raise HTTPException(404, str(exc)) from None

    return CalibrationProfileResponse(
        arm_id=profile.arm_id,
        zeros=profile.zeros,
        ranges=profile.ranges,
        inversions=profile.inversions,
        gravity=profile.gravity,
    )


@router.delete("/{arm_id}/profile")
def clear_profile(arm_id: str) -> dict:
    """Delete all calibration data for an arm."""
    cal_mgr, reg = _get_managers()
    if arm_id not in reg.arms:
        raise HTTPException(404, f"Arm '{arm_id}' not found")

    try:
        cal_mgr.delete_profile(arm_id)
    except CalibrationError as exc:
        raise HTTPException(404, str(exc)) from None

    reg.set_arm_calibrated(arm_id, False)
    logger.info("Cleared calibration for %s", arm_id)
    return {"status": "ok", "armId": arm_id}
