"""Joint mapping between leader and follower arms.

Handles cross-motor-type joint name mapping (e.g., Dynamixel joint_N ->
Damiao base/linkN) and value conversion across different motor encodings.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# Dynamixel XL330 leaders use joint_N naming; Damiao followers use base/linkN naming
DYNAMIXEL_TO_DAMIAO_JOINT_MAP: dict[str, str] = {
    "joint_1": "base",
    "joint_2": "link1",
    "joint_3": "link2",
    "joint_4": "link3",
    "joint_5": "link4",
    "joint_6": "link5",
    "gripper": "gripper",
}

# Standard 7-DOF joint name template
JOINT_NAMES_TEMPLATE: list[str] = [
    "base",
    "link1",
    "link2",
    "link3",
    "link4",
    "link5",
    "gripper",
]


class ValueMode(str, Enum):  # noqa: UP042
    """How to convert leader values to follower values."""

    FLOAT = "float"  # Damiao: passthrough radians
    RAD_TO_PERCENT = "rad_to_percent"  # Dynamixel -> Feetech
    INT = "int"  # Legacy Feetech -> Feetech (integer ticks)


class JointMapper:
    """Maps leader arm joints to follower arm joints.

    Handles two mapping modes:
    - Pairing-based: Uses explicit pairings from ArmRegistryService.
    - Legacy: Side-based (left_leader -> left_follower).

    Args:
        arm_registry: Optional ArmRegistryService for pairing-based mapping.
    """

    def __init__(self, arm_registry: Any | None = None) -> None:
        self._arm_registry = arm_registry
        self.joint_mapping: dict[str, str] = {}
        self.value_mode: ValueMode = ValueMode.INT
        self.leader_cal_ranges: dict[str, tuple[float, float]] = {}
        self._has_damiao_follower: bool = False

    def compute_mappings(
        self,
        pairings: list[dict],
        active_arms: list[str] | None = None,
        leader: Any | None = None,
    ) -> None:
        """Compute joint mappings from explicit pairings.

        Args:
            pairings: List of pairing dicts with leader_id/follower_id.
            active_arms: Optional filter for active arm IDs.
            leader: Leader instance for calibration range lookup.
        """
        self.joint_mapping = {}
        registry = self._arm_registry

        for pairing in pairings:
            leader_id = pairing["leader_id"]
            follower_id = pairing["follower_id"]

            if active_arms is not None and (
                leader_id not in active_arms or follower_id not in active_arms
            ):
                continue

            leader_arm = registry.arms.get(leader_id) if registry else None
            follower_arm = registry.arms.get(follower_id) if registry else None

            is_dyn_leader = leader_arm and leader_arm.motor_type.value in (
                "dynamixel_xl330",
                "dynamixel_xl430",
            )
            is_dam_follower = follower_arm and follower_arm.motor_type.value == "damiao"
            is_fee_follower = follower_arm and follower_arm.motor_type.value == "sts3215"

            is_sts_leader = leader_arm and leader_arm.motor_type.value == "sts3215"

            if is_dyn_leader and is_dam_follower:
                for dyn_name, dam_name in DYNAMIXEL_TO_DAMIAO_JOINT_MAP.items():
                    self.joint_mapping[f"{dyn_name}.pos"] = f"{dam_name}.pos"
                self._has_damiao_follower = True
                self.value_mode = ValueMode.FLOAT
            elif is_dyn_leader and is_fee_follower:
                for dyn_name, dam_name in DYNAMIXEL_TO_DAMIAO_JOINT_MAP.items():
                    self.joint_mapping[f"{dyn_name}.pos"] = f"{dam_name}.pos"
                self.value_mode = ValueMode.RAD_TO_PERCENT
                self._precompute_cal_ranges(leader)
            elif is_sts_leader and is_dam_follower:
                # Umbra leader → Damiao follower: both use base/linkN naming
                for name in JOINT_NAMES_TEMPLATE:
                    self.joint_mapping[f"{name}.pos"] = f"{name}.pos"
                self._has_damiao_follower = True
                self.value_mode = ValueMode.FLOAT
            elif is_sts_leader and is_fee_follower:
                # Umbra leader → Umbra follower: identity mapping
                for name in JOINT_NAMES_TEMPLATE:
                    self.joint_mapping[f"{name}.pos"] = f"{name}.pos"
                self.value_mode = ValueMode.FLOAT
            else:
                # Legacy prefix-based mapping for same-type arms
                leader_prefix = _get_arm_prefix(leader_id)
                follower_prefix = _get_arm_prefix(follower_id)
                for name in JOINT_NAMES_TEMPLATE:
                    self.joint_mapping[f"{leader_prefix}{name}.pos"] = (
                        f"{follower_prefix}{name}.pos"
                    )

        logger.info(
            "Joint mapping: %d joints from %d pairings (mode=%s)",
            len(self.joint_mapping),
            len(pairings),
            self.value_mode.value,
        )

    def compute_mappings_legacy(self, active_arms: list[str] | None = None) -> None:
        """Compute joint mappings using legacy side-based convention.

        Args:
            active_arms: Optional filter for active arm IDs.
        """
        self.joint_mapping = {}

        def is_active(side: str, group: str) -> bool:
            if active_arms is None:
                return True
            return f"{side}_{group}" in active_arms

        for side in ("left", "right", "default"):
            prefix = "" if side == "default" else f"{side}_"
            if is_active(side, "leader") and is_active(side, "follower"):
                for name in JOINT_NAMES_TEMPLATE:
                    key = f"{prefix}{name}.pos"
                    self.joint_mapping[key] = key

        logger.info("Legacy mapping: %d joints", len(self.joint_mapping))

    def convert_value(
        self,
        value: float,
        follower_key: str,
        leader_key: str = "",
        leader_start_rad: dict[str, float] | None = None,
        follower_start_pos: dict[str, float] | None = None,
        rad_to_percent_scale: dict[str, float] | None = None,
    ) -> float:
        """Convert a leader value to follower value based on current mode.

        Args:
            value: Raw leader position value.
            follower_key: Follower joint key (e.g., "base.pos").
            leader_key: Leader joint key for delta-based fallback.
            leader_start_rad: Start positions for delta tracking.
            follower_start_pos: Follower start positions for delta tracking.
            rad_to_percent_scale: Per-joint scaling factors.

        Returns:
            Converted value for the follower.
        """
        if self.value_mode == ValueMode.FLOAT:
            return value

        if self.value_mode == ValueMode.RAD_TO_PERCENT:
            if "gripper" in follower_key:
                return value * 100.0

            if follower_key in self.leader_cal_ranges:
                rmin, rmax = self.leader_cal_ranges[follower_key]
                leader_ticks = (value + np.pi) * 4096.0 / (2 * np.pi)
                return ((leader_ticks - rmin) / (rmax - rmin)) * 200 - 100

            # Fallback: delta-based tracking
            if (
                leader_start_rad
                and follower_start_pos
                and leader_key in leader_start_rad
                and follower_key in follower_start_pos
            ):
                delta = value - leader_start_rad[leader_key]
                scale = (rad_to_percent_scale or {}).get(follower_key, 100.0 / np.pi)
                return follower_start_pos[follower_key] + delta * scale

            scale = (rad_to_percent_scale or {}).get(follower_key, 100.0 / np.pi)
            return value * scale

        # ValueMode.INT — legacy Feetech
        return int(value)

    @property
    def has_damiao_follower(self) -> bool:
        """Whether any mapped follower is a Damiao arm."""
        return self._has_damiao_follower

    def _precompute_cal_ranges(self, leader: Any | None) -> None:
        """Extract calibration ranges from leader for absolute mapping."""
        if not leader or not hasattr(leader, "calibration") or not leader.calibration:
            return

        for dyn_name, dam_name in DYNAMIXEL_TO_DAMIAO_JOINT_MAP.items():
            if dyn_name == "gripper":
                continue
            l_cal = leader.calibration.get(dyn_name)
            if l_cal:
                f_key = f"{dam_name}.pos"
                self.leader_cal_ranges[f_key] = (l_cal.range_min, l_cal.range_max)

        if self.leader_cal_ranges:
            logger.info(
                "Absolute mapping: %d joints from leader calibration",
                len(self.leader_cal_ranges),
            )
        else:
            logger.warning("Leader calibration missing — falling back to delta tracking")


def _get_arm_prefix(arm_id: str) -> str:
    """Get the joint name prefix for an arm ID."""
    if arm_id.startswith("left_"):
        return "left_"
    elif arm_id.startswith("right_"):
        return "right_"
    elif arm_id in ("damiao_follower", "damiao_leader"):
        return ""
    else:
        return f"{arm_id}_"
