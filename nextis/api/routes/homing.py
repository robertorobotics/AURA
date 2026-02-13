"""Homing routes — safe return-to-home for Damiao follower arms.

Runs ``homing_loop`` in a background thread with cancellation via
``threading.Event``.
"""

from __future__ import annotations

import logging
import threading

from fastapi import APIRouter, HTTPException

from nextis.api.schemas import HomingStartRequest
from nextis.control.homing import homing_loop
from nextis.hardware.types import ConnectionStatus, MotorType

logger = logging.getLogger(__name__)

router = APIRouter()

# Module-level state for the active homing operation.
_homing_thread: threading.Thread | None = None
_cancel_event: threading.Event = threading.Event()

# Default home position for AIRA Zero (radians, all joints centered).
DEFAULT_HOME_POS: dict[str, float] = {
    "base": 0.0,
    "link1": 0.0,
    "link2": 0.0,
    "link3": 0.0,
    "link4": 0.0,
    "link5": 0.0,
    "gripper": 0.0,
}


# ------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------


@router.post("/start")
async def start_homing(request: HomingStartRequest) -> dict[str, str]:
    """Start homing a follower arm in a background thread.

    The arm must be a connected Damiao follower. Returns immediately;
    homing runs asynchronously for up to ``request.duration`` seconds,
    then disables motors.
    """
    global _homing_thread  # noqa: PLW0603

    if _homing_thread is not None and _homing_thread.is_alive():
        raise HTTPException(status_code=409, detail="Homing already in progress")

    from nextis.api.routes.hardware import get_registry

    registry = get_registry()
    arm = registry.arms.get(request.arm_id)

    if arm is None:
        raise HTTPException(status_code=404, detail=f"Arm '{request.arm_id}' not found")
    if arm.motor_type != MotorType.DAMIAO:
        raise HTTPException(
            status_code=400, detail="Homing is only supported for Damiao follower arms"
        )
    if arm.role.value != "follower":
        raise HTTPException(status_code=400, detail="Homing is only supported for follower arms")
    if registry.arm_status.get(request.arm_id) != ConnectionStatus.CONNECTED:
        raise HTTPException(status_code=400, detail=f"Arm '{request.arm_id}' is not connected")

    robot = registry.get_arm_instance(request.arm_id)
    if robot is None:
        raise HTTPException(status_code=500, detail="Arm instance not available")

    home_pos = request.home_pos or DEFAULT_HOME_POS
    _cancel_event.clear()

    _homing_thread = threading.Thread(
        target=homing_loop,
        kwargs={
            "robot": robot,
            "home_pos": home_pos,
            "duration": request.duration,
            "homing_vel": request.velocity,
            "cancel_check": _cancel_event.is_set,
        },
        daemon=True,
        name="HomingLoop",
    )
    _homing_thread.start()
    logger.info("Homing started for arm %s", request.arm_id)
    return {"status": "ok", "armId": request.arm_id}


@router.post("/stop")
async def stop_homing() -> dict[str, str]:
    """Cancel the active homing operation."""
    if _homing_thread is None or not _homing_thread.is_alive():
        raise HTTPException(status_code=409, detail="No active homing operation")

    _cancel_event.set()
    logger.info("Homing cancel requested")
    return {"status": "ok"}
