"""Hardware type definitions.

Data models for arm configuration, motor types, and arm pairings.
These are pure data -- no hardware communication logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class MotorType(Enum):
    """Supported motor bus types."""

    DAMIAO = "damiao"
    DYNAMIXEL = "dynamixel"
    FEETECH = "feetech"


class ArmRole(Enum):
    """Role of an arm in the system."""

    LEADER = "leader"
    FOLLOWER = "follower"


@dataclass
class ArmDefinition:
    """Configuration for a single robotic arm.

    Attributes:
        id: Unique arm identifier (e.g., "left_follower").
        name: Human-readable name.
        role: Whether this arm is a leader (human-operated) or follower.
        motor_type: Type of motors in this arm.
        port: Serial port or CAN interface (e.g., "/dev/ttyUSB0", "can0").
        motor_ids: Ordered list of motor IDs on the bus.
        joint_names: Human-readable joint names matching motor_ids order.
        calibration_dir: Path to calibration profile directory.
    """

    id: str
    name: str
    role: ArmRole
    motor_type: MotorType
    port: str
    motor_ids: list[int] = field(default_factory=list)
    joint_names: list[str] = field(default_factory=list)
    calibration_dir: str | None = None


@dataclass
class Pairing:
    """A leader-follower arm pairing for teleoperation.

    Attributes:
        id: Unique pairing identifier.
        leader_id: ArmDefinition ID for the leader arm.
        follower_id: ArmDefinition ID for the follower arm.
        joint_mapping: Maps leader joint names to follower joint names.
            If empty, assumes 1:1 positional mapping.
    """

    id: str
    leader_id: str
    follower_id: str
    joint_mapping: dict[str, str] = field(default_factory=dict)
