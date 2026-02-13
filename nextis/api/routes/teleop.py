"""Teleoperation control routes.

Manages a single TeleopLoop instance.  Supports mock mode for testing
without hardware and real mode (not yet implemented) via arm_registry.
"""

from __future__ import annotations

import logging
import threading
import uuid

from fastapi import APIRouter, HTTPException, Query

from nextis.api.schemas import TeleopStartRequest, TeleopState
from nextis.control.teleop_loop import TeleopLoop

logger = logging.getLogger(__name__)

router = APIRouter()

# Module-level singleton — one teleop session at a time.
_teleop_loop: TeleopLoop | None = None
_session_id: str | None = None
_session_arms: list[str] = []
_session_mock: bool = False


# ------------------------------------------------------------------
# Public accessor (used by recording routes)
# ------------------------------------------------------------------


def get_teleop_loop() -> TeleopLoop | None:
    """Return the current teleop loop instance, or None."""
    return _teleop_loop


# ------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------


@router.post("/start")
async def start_teleop(
    request: TeleopStartRequest,
    mock: bool = Query(False, description="Use mock hardware"),
) -> dict[str, str]:
    """Start a teleoperation session.

    Args:
        request: Body with arm selection.
        mock: If True, use MockRobot + MockLeader instead of real hardware.
    """
    global _teleop_loop, _session_id, _session_arms, _session_mock  # noqa: PLW0603

    if _teleop_loop is not None and _teleop_loop.is_running:
        raise HTTPException(status_code=409, detail="Teleop session already active")

    if mock:
        robot, leader, safety, mapper, gripper_ff, joint_ff = _create_mock_stack()
    else:
        try:
            robot, leader, safety, mapper, gripper_ff, joint_ff = _create_real_stack(request.arms)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    _teleop_loop = TeleopLoop(
        robot=robot,
        leader=leader,
        safety=safety,
        joint_mapper=mapper,
        gripper_ff=gripper_ff,
        joint_ff=joint_ff,
    )
    _teleop_loop.start()
    _session_id = str(uuid.uuid4())[:8]
    _session_arms = request.arms
    _session_mock = mock

    logger.info("Teleop session started: id=%s mock=%s arms=%s", _session_id, mock, request.arms)
    return {"status": "ok", "sessionId": _session_id}


@router.post("/stop")
async def stop_teleop() -> dict[str, str]:
    """Stop the current teleoperation session."""
    global _teleop_loop, _session_id  # noqa: PLW0603

    if _teleop_loop is None or not _teleop_loop.is_running:
        raise HTTPException(status_code=409, detail="No active teleop session")

    # Auto-stop any active recording to prevent orphaned threads.
    try:
        from nextis.api.routes.recording import _recorder

        if _recorder is not None and _recorder.is_recording:
            _recorder.stop()
            logger.warning("Auto-stopped recording when teleop stopped")
    except ImportError:
        pass

    _teleop_loop.stop()
    old_id = _session_id
    _teleop_loop = None
    _session_id = None

    logger.info("Teleop session stopped: id=%s", old_id)
    return {"status": "ok"}


@router.get("/state", response_model=TeleopState)
async def get_teleop_state() -> TeleopState:
    """Return current teleop session state."""
    if _teleop_loop is None or not _teleop_loop.is_running:
        return TeleopState()

    return TeleopState(
        active=True,
        arms=_session_arms,
        session_id=_session_id,
        mock=_session_mock,
        loop_count=_teleop_loop.loop_count,
    )


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


def _create_mock_stack() -> tuple:
    """Create MockRobot, MockLeader, SafetyLayer, and JointMapper for mock mode."""
    from nextis.control.joint_mapping import JointMapper, ValueMode
    from nextis.control.safety import SafetyLayer
    from nextis.hardware.mock import MOCK_JOINT_NAMES, MockLeader, MockRobot

    robot = MockRobot()
    leader = MockLeader()
    safety = SafetyLayer(robot_lock=threading.Lock())
    mapper = JointMapper()
    mapper.joint_mapping = {f"{n}.pos": f"{n}.pos" for n in MOCK_JOINT_NAMES}
    mapper.value_mode = ValueMode.FLOAT

    return robot, leader, safety, mapper, None, None


def _create_real_stack(arm_selection: list[str]) -> tuple:
    """Create real hardware stack from connected arms in the ArmRegistryService.

    Finds a connected leader-follower pairing, retrieves robot and leader
    instances, and builds the full control stack with joint mapping and
    force feedback.

    Args:
        arm_selection: Arm IDs to use, or ``["default"]`` for first pairing.

    Returns:
        Tuple of (robot, leader, safety, mapper, gripper_ff, joint_ff).

    Raises:
        ValueError: If no connected pairing found or instances unavailable.
    """
    from nextis.api.routes.hardware import get_registry
    from nextis.control.force_feedback import GripperForceFeedback, JointForceFeedback
    from nextis.control.joint_mapping import JointMapper
    from nextis.control.safety import SafetyLayer
    from nextis.hardware.types import ConnectionStatus, MotorType

    registry = get_registry()

    # Find a pairing where both arms are connected.
    pairing = None
    for p in registry.pairings:
        leader_ok = registry.arm_status.get(p.leader_id) == ConnectionStatus.CONNECTED
        follower_ok = registry.arm_status.get(p.follower_id) == ConnectionStatus.CONNECTED
        if not (leader_ok and follower_ok):
            continue
        # If caller specified specific arm IDs, filter by them.
        if (
            arm_selection != ["default"]
            and p.leader_id not in arm_selection
            and p.follower_id not in arm_selection
        ):
            continue
        pairing = p
        break

    if pairing is None:
        raise ValueError(
            "No connected arm pairing found. "
            "Connect both leader and follower via POST /hardware/connect first."
        )

    robot = registry.get_arm_instance(pairing.follower_id)
    leader = registry.get_arm_instance(pairing.leader_id)

    if robot is None or leader is None:
        raise ValueError(
            f"Arm instances not available for pairing '{pairing.name}'. "
            "Did connect_arm succeed for both arms?"
        )

    safety = SafetyLayer(robot_lock=threading.Lock())

    mapper = JointMapper(arm_registry=registry)
    mapper.compute_mappings(
        pairings=registry.get_pairings(),
        active_arms=[pairing.leader_id, pairing.follower_id],
        leader=leader,
    )

    # Enable force feedback for Damiao followers.
    gripper_ff = None
    joint_ff = None
    follower_arm = registry.arms.get(pairing.follower_id)
    if follower_arm and follower_arm.motor_type == MotorType.DAMIAO:
        gripper_ff = GripperForceFeedback()
        joint_ff = JointForceFeedback()
        logger.info("Force feedback enabled for Damiao follower %s", pairing.follower_id)

    return robot, leader, safety, mapper, gripper_ff, joint_ff
