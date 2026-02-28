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


def _ensure_leader_modes(leader: object, leader_arm: object) -> None:
    """Verify Dynamixel leader motors are in CURRENT_POSITION mode.

    DynamixelLeader.configure() sets this during connect(), but a motor
    power-cycle between connect and teleop start can reset the mode.
    This is a defensive re-check.

    Args:
        leader: Leader arm instance (DynamixelLeader or other).
        leader_arm: ArmDefinition for the leader.
    """
    from nextis.hardware.types import MotorType

    if leader_arm.motor_type not in (MotorType.DYNAMIXEL_XL330, MotorType.DYNAMIXEL_XL430):
        return
    if not hasattr(leader, "bus"):
        return

    bus = leader.bus
    # Gripper and joint_4 need CURRENT_POSITION (5) for force feedback:
    # - gripper: allows Goal_Current writes for grip resistance
    # - joint_4: allows virtual spring feedback via Goal_Current + Goal_Position
    for motor_name in ("gripper", "joint_4"):
        if motor_name not in bus.motors:
            continue
        try:
            current_mode = bus.read("Operating_Mode", motor_name, normalize=False)
            if current_mode != 5:  # 5 = CURRENT_BASED_POSITION
                logger.warning(
                    "%s in mode %d, expected CURRENT_POSITION (5) — re-configuring",
                    motor_name,
                    current_mode,
                )
                bus.write("Torque_Enable", motor_name, 0, normalize=False)
                bus.write("Operating_Mode", motor_name, 5, normalize=False)
                bus.write("Current_Limit", motor_name, 1750, normalize=False)
                # Set Goal_Position to current to prevent violent jump on torque-enable
                cur_pos = bus.read("Present_Position", motor_name, normalize=False)
                bus.write("Goal_Position", motor_name, int(cur_pos), normalize=False)
                bus.write("Torque_Enable", motor_name, 1, normalize=False)
            else:
                logger.info("%s: CURRENT_POSITION mode confirmed", motor_name)
        except Exception as e:
            logger.warning("Could not verify %s operating mode: %s", motor_name, e)


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

    # ── 1. Find a pairing where both arms are connected ───────────
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
        statuses = {
            aid: registry.arm_status.get(aid, ConnectionStatus.DISCONNECTED).value
            for p in registry.pairings
            for aid in (p.leader_id, p.follower_id)
        }
        raise ValueError(
            "No connected arm pairing found. "
            "Connect both leader and follower via POST /hardware/connect first. "
            f"Current statuses: {statuses}"
        )

    leader_arm = registry.arms.get(pairing.leader_id)
    follower_arm = registry.arms.get(pairing.follower_id)
    logger.info(
        "Using pairing '%s': leader=%s (%s), follower=%s (%s)",
        pairing.name,
        pairing.leader_id,
        leader_arm.motor_type.value if leader_arm else "?",
        pairing.follower_id,
        follower_arm.motor_type.value if follower_arm else "?",
    )

    # ── 2. Retrieve arm instances ─────────────────────────────────
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

    # ── 3. Verify leader operating modes ──────────────────────────
    if leader_arm:
        _ensure_leader_modes(leader, leader_arm)

    # ── 4. Build control stack ────────────────────────────────────
    safety = SafetyLayer(robot_lock=threading.Lock())

    mapper = JointMapper(arm_registry=registry)
    mapper.compute_mappings(
        pairings=registry.get_pairings(),
        active_arms=[pairing.leader_id, pairing.follower_id],
        leader=leader,
    )

    if not mapper.joint_mapping:
        raise ValueError(
            f"Joint mapping produced 0 joints for pairing '{pairing.name}'. "
            f"Leader type={leader_arm.motor_type.value if leader_arm else '?'}, "
            f"follower type={follower_arm.motor_type.value if follower_arm else '?'}. "
            "This motor type combination may not be supported yet."
        )

    # Enable force feedback for Damiao followers.
    gripper_ff = None
    joint_ff = None
    if follower_arm and follower_arm.motor_type == MotorType.DAMIAO:
        gripper_ff = GripperForceFeedback()
        joint_ff = JointForceFeedback()
        logger.info("Force feedback enabled for Damiao follower %s", pairing.follower_id)

    return robot, leader, safety, mapper, gripper_ff, joint_ff
