"""Teleoperation control routes.

Manages a single TeleopLoop instance stored on SystemState.  Supports
mock mode for testing without hardware and real mode via arm_registry.
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


# ------------------------------------------------------------------
# Public accessor (used by recording routes and e-stop)
# ------------------------------------------------------------------


def get_teleop_loop() -> TeleopLoop | None:
    """Return the current teleop loop instance, or None."""
    from nextis.state import get_state

    return get_state().teleop_loop


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
    from nextis.state import get_state

    state = get_state()

    if state.teleop_loop is not None and state.teleop_loop.is_running:
        raise HTTPException(status_code=409, detail="Teleop session already active")

    if mock:
        robot, leader, safety, mapper, gripper_ff, joint_ff = _create_mock_stack()
    else:
        try:
            robot, leader, safety, mapper, gripper_ff, joint_ff = _create_real_stack(request.arms)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    loop = TeleopLoop(
        robot=robot,
        leader=leader,
        safety=safety,
        joint_mapper=mapper,
        gripper_ff=gripper_ff,
        joint_ff=joint_ff,
    )
    loop.start()

    state.teleop_loop = loop
    state.teleop_session_id = str(uuid.uuid4())[:8]
    state.teleop_session_arms = request.arms
    state.teleop_session_mock = mock

    logger.info(
        "Teleop session started: id=%s mock=%s arms=%s",
        state.teleop_session_id,
        mock,
        request.arms,
    )
    return {"status": "ok", "sessionId": state.teleop_session_id}


@router.post("/stop")
async def stop_teleop() -> dict[str, str]:
    """Stop the current teleoperation session."""
    from nextis.state import get_state

    state = get_state()

    if state.teleop_loop is None or not state.teleop_loop.is_running:
        raise HTTPException(status_code=409, detail="No active teleop session")

    # Auto-stop any active recording to prevent orphaned threads.
    if state.recorder is not None and state.recorder.is_recording:
        try:
            state.recorder.stop()
            logger.warning("Auto-stopped recording when teleop stopped")
        except Exception:
            pass
        state.recorder = None

    state.teleop_loop.stop()
    old_id = state.teleop_session_id
    state.teleop_loop = None
    state.teleop_session_id = None

    logger.info("Teleop session stopped: id=%s", old_id)
    return {"status": "ok"}


@router.get("/state", response_model=TeleopState)
async def get_teleop_state() -> TeleopState:
    """Return current teleop session state."""
    from nextis.state import get_state

    state = get_state()

    if state.teleop_loop is None or not state.teleop_loop.is_running:
        return TeleopState()

    return TeleopState(
        active=True,
        arms=state.teleop_session_arms,
        session_id=state.teleop_session_id,
        mock=state.teleop_session_mock,
        loop_count=state.teleop_loop.loop_count,
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
        missing = []
        if robot is None:
            missing.append(f"follower '{pairing.follower_id}'")
        if leader is None:
            missing.append(f"leader '{pairing.leader_id}'")
        raise ValueError(
            f"Arm instances not available for {', '.join(missing)} "
            f"in pairing '{pairing.name}'. "
            "Ensure connect_arm succeeded (check lerobot availability if it failed)."
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
