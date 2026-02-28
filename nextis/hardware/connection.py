"""Arm connection factory — creates lerobot hardware instances.

Maps (MotorType, ArmRole) to the appropriate lerobot Robot or Teleoperator
config and class.  Passes ``calibration_dir`` so lerobot uses the project's
``configs/calibration/{arm_id}/`` directory instead of its HF cache fallback.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from nextis.config import CALIBRATION_DIR
from nextis.errors import HardwareError
from nextis.hardware.types import ArmDefinition, ArmRole, MotorType

logger = logging.getLogger(__name__)

_LEROBOT_HINT = (
    "lerobot not found. Ensure lerobot/src is on PYTHONPATH. "
    "See start.sh or run with PYTHONPATH=lerobot/src:$PYTHONPATH"
)


def _calibration_dir_for(arm: ArmDefinition) -> Path:
    """Return the calibration directory for a specific arm.

    Args:
        arm: The arm definition to compute the calibration path for.

    Returns:
        Path to ``configs/calibration/{arm.id}``.
    """
    return CALIBRATION_DIR / arm.id


def create_arm_instance(arm: ArmDefinition) -> Any:
    """Create a lerobot Robot or Teleoperator instance for the given arm.

    Factory that lazily imports lerobot hardware classes based on
    ``arm.motor_type`` and ``arm.role``.  Passes ``calibration_dir`` to
    all config constructors so calibration files are read from / written to
    the project's ``configs/calibration/{arm.id}/`` directory.

    Args:
        arm: Arm definition specifying motor type, role, port, etc.

    Returns:
        Connected lerobot Robot or Teleoperator instance, or ``None``
        for unsupported motor_type + role combinations.

    Raises:
        HardwareError: If lerobot is not importable.
    """
    cal_dir = _calibration_dir_for(arm)

    if arm.motor_type == MotorType.STS3215:
        return _create_sts3215(arm, cal_dir)

    if arm.motor_type == MotorType.DAMIAO:
        return _create_damiao(arm, cal_dir)

    if arm.motor_type in (MotorType.DYNAMIXEL_XL330, MotorType.DYNAMIXEL_XL430):
        return _create_dynamixel(arm, cal_dir)

    logger.warning("Unknown motor type: %s", arm.motor_type)
    return None


# ---------------------------------------------------------------------------
# Private helpers — one per motor family
# ---------------------------------------------------------------------------


def _create_sts3215(arm: ArmDefinition, cal_dir: Path) -> Any:
    """Create STS3215 (Umbra) follower or leader instance."""
    if arm.role == ArmRole.FOLLOWER:
        try:
            from lerobot.robots.umbra_follower import UmbraFollowerRobot
            from lerobot.robots.umbra_follower.config_umbra_follower import (
                UmbraFollowerConfig,
            )
        except ImportError as e:
            raise HardwareError(f"{_LEROBOT_HINT} ({e})") from e

        config = UmbraFollowerConfig(
            id=arm.id,
            port=arm.port,
            cameras={},
            calibration_dir=cal_dir,
        )
        robot = UmbraFollowerRobot(config)
        robot.connect(calibrate=False)
        return robot

    # STS3215 leader
    try:
        from lerobot.teleoperators.umbra_leader import UmbraLeaderRobot
        from lerobot.teleoperators.umbra_leader.config_umbra_leader import (
            UmbraLeaderConfig,
        )
    except ImportError as e:
        raise HardwareError(f"{_LEROBOT_HINT} ({e})") from e

    config = UmbraLeaderConfig(
        id=arm.id,
        port=arm.port,
        calibration_dir=cal_dir,
    )
    leader = UmbraLeaderRobot(config)
    leader.connect(calibrate=False)
    return leader


def _create_damiao(arm: ArmDefinition, cal_dir: Path) -> Any | None:
    """Create Damiao follower instance (leader not supported)."""
    if arm.role != ArmRole.FOLLOWER:
        logger.warning("Damiao leader arms not yet supported")
        return None

    try:
        from lerobot.robots.damiao_follower import DamiaoFollowerRobot
        from lerobot.robots.damiao_follower.config_damiao_follower import (
            DamiaoFollowerConfig,
        )
    except ImportError as e:
        raise HardwareError(f"{_LEROBOT_HINT} ({e})") from e

    config = DamiaoFollowerConfig(
        id=arm.id,
        port=arm.port,
        velocity_limit=arm.config.get("velocity_limit", 0.3),
        cameras={},
        calibration_dir=cal_dir,
    )
    robot = DamiaoFollowerRobot(config)
    robot.connect()
    return robot


def _create_dynamixel(arm: ArmDefinition, cal_dir: Path) -> Any | None:
    """Create Dynamixel leader instance (follower not supported)."""
    if arm.role != ArmRole.LEADER:
        logger.warning("Dynamixel follower arms not typical use case")
        return None

    try:
        from lerobot.teleoperators.dynamixel_leader import DynamixelLeader
        from lerobot.teleoperators.dynamixel_leader.config_dynamixel_leader import (
            DynamixelLeaderConfig,
        )
    except ImportError as e:
        raise HardwareError(f"{_LEROBOT_HINT} ({e})") from e

    config = DynamixelLeaderConfig(
        id=arm.id,
        port=arm.port,
        structural_design=arm.structural_design or "",
        calibration_dir=cal_dir,
    )
    leader = DynamixelLeader(config)
    leader.connect(calibrate=False)
    return leader
