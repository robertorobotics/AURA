"""Arm registry service — central management for multi-arm robotics systems.

Handles arm registration, connection lifecycle, leader-follower pairing,
and YAML-based configuration persistence. Does NOT handle port scanning
or motor recovery (those are separate concerns).
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

import yaml

from nextis.errors import HardwareError
from nextis.hardware.types import (
    ArmDefinition,
    ArmRole,
    ConnectionStatus,
    MotorType,
    Pairing,
)

logger = logging.getLogger(__name__)


class ArmRegistryService:
    """Central service for arm management.

    Handles loading arm definitions from YAML config, managing connections
    to individual arms, and storing leader-follower pairings.

    Args:
        config_path: Path to the YAML configuration file.
    """

    def __init__(self, config_path: str | Path | None = None) -> None:
        if config_path is None:
            from nextis.config import CONFIG_PATH, _resolve_config_path

            resolved = _resolve_config_path()
            self.config_path = resolved if resolved is not None else CONFIG_PATH
        else:
            self.config_path = Path(config_path)
        self.arms: dict[str, ArmDefinition] = {}
        self.pairings: list[Pairing] = []
        self.arm_instances: dict[str, Any] = {}
        self.arm_status: dict[str, ConnectionStatus] = {}
        self._lock = threading.Lock()
        self._config_data: dict = {}

        self._load_config()

    def _load_config(self) -> None:
        """Load configuration from settings.yaml."""
        if not self.config_path.exists():
            logger.warning("Config file not found: %s", self.config_path)
            return

        with open(self.config_path) as f:
            self._config_data = yaml.safe_load(f) or {}

        if "arms" in self._config_data:
            self._load_new_format()
        else:
            self._migrate_legacy_config()

    def _load_new_format(self) -> None:
        """Load arms from new-style configuration."""
        arms_config = self._config_data.get("arms", {})

        for arm_id, arm_cfg in arms_config.items():
            try:
                arm = ArmDefinition(
                    id=arm_id,
                    name=arm_cfg.get("name", arm_id),
                    role=ArmRole(arm_cfg.get("role", "follower")),
                    motor_type=MotorType(arm_cfg.get("motor_type", "sts3215")),
                    port=arm_cfg.get("port", ""),
                    enabled=arm_cfg.get("enabled", True),
                    structural_design=arm_cfg.get("structural_design"),
                    config=arm_cfg.get("config", {}),
                    calibrated=arm_cfg.get("calibrated", False),
                )
                self.arms[arm_id] = arm
                self.arm_status[arm_id] = ConnectionStatus.DISCONNECTED
                logger.info("Loaded arm: %s (%s) — %s", arm.name, arm_id, arm.motor_type.value)
            except Exception as e:
                logger.error("Failed to load arm %s: %s", arm_id, e)

        pairings_config = self._config_data.get("pairings", [])
        for pairing_cfg in pairings_config:
            try:
                pairing = Pairing(
                    leader_id=pairing_cfg["leader"],
                    follower_id=pairing_cfg["follower"],
                    name=pairing_cfg.get(
                        "name", f"{pairing_cfg['leader']} -> {pairing_cfg['follower']}"
                    ),
                )
                self.pairings.append(pairing)
                logger.info("Loaded pairing: %s", pairing.name)
            except Exception as e:
                logger.error("Failed to load pairing: %s", e)

    def _migrate_legacy_config(self) -> None:
        """Convert old robot/teleop config to new arms format."""
        robot_cfg = self._config_data.get("robot", {})
        teleop_cfg = self._config_data.get("teleop", {})
        robot_type = robot_cfg.get("type", "")

        if robot_type == "bi_umbra_follower":
            for side in ("left", "right"):
                port = robot_cfg.get(f"{side}_arm_port")
                if port:
                    arm_id = f"{side}_follower"
                    self.arms[arm_id] = ArmDefinition(
                        id=arm_id,
                        name=f"{side.title()} Follower",
                        role=ArmRole.FOLLOWER,
                        motor_type=MotorType.STS3215,
                        port=port,
                        structural_design="umbra_7dof",
                    )
                    self.arm_status[arm_id] = ConnectionStatus.DISCONNECTED
        elif robot_type == "damiao_follower":
            self.arms["damiao_follower"] = ArmDefinition(
                id="damiao_follower",
                name="Damiao Follower",
                role=ArmRole.FOLLOWER,
                motor_type=MotorType.DAMIAO,
                port=robot_cfg.get("port", ""),
                structural_design="damiao_7dof",
                config=robot_cfg.get("config", {}),
            )
            self.arm_status["damiao_follower"] = ConnectionStatus.DISCONNECTED

        teleop_type = teleop_cfg.get("type", "")
        if teleop_type == "bi_umbra_leader":
            for side in ("left", "right"):
                port = teleop_cfg.get(f"{side}_arm_port")
                if port:
                    arm_id = f"{side}_leader"
                    self.arms[arm_id] = ArmDefinition(
                        id=arm_id,
                        name=f"{side.title()} Leader",
                        role=ArmRole.LEADER,
                        motor_type=MotorType.STS3215,
                        port=port,
                        structural_design="umbra_7dof",
                    )
                    self.arm_status[arm_id] = ConnectionStatus.DISCONNECTED

        # Create side-based pairings
        for side in ("left", "right"):
            leader_id = f"{side}_leader"
            follower_id = f"{side}_follower"
            if leader_id in self.arms and follower_id in self.arms:
                self.pairings.append(
                    Pairing(
                        leader_id=leader_id,
                        follower_id=follower_id,
                        name=f"{side.title()} Pair",
                    )
                )

        logger.info(
            "Migrated legacy config: %d arms, %d pairings",
            len(self.arms),
            len(self.pairings),
        )

    # --- Query Methods ---

    def get_all_arms(self) -> list[dict]:
        """Return all arms with their current status."""
        result = []
        for arm_id, arm in self.arms.items():
            arm_dict = arm.to_dict()
            arm_dict["status"] = self.arm_status.get(arm_id, ConnectionStatus.DISCONNECTED).value
            result.append(arm_dict)
        return result

    def get_arm(self, arm_id: str) -> dict | None:
        """Get a specific arm by ID."""
        if arm_id not in self.arms:
            return None
        arm_dict = self.arms[arm_id].to_dict()
        arm_dict["status"] = self.arm_status.get(arm_id, ConnectionStatus.DISCONNECTED).value
        return arm_dict

    def get_leaders(self) -> list[dict]:
        """Return all leader arms."""
        return [a for a in self.get_all_arms() if a["role"] == "leader"]

    def get_followers(self) -> list[dict]:
        """Return all follower arms."""
        return [a for a in self.get_all_arms() if a["role"] == "follower"]

    def get_pairings(self) -> list[dict]:
        """Return all leader-follower pairings."""
        return [p.to_dict() for p in self.pairings]

    def get_active_pairings(self, active_arm_ids: list[str] | None = None) -> list[dict]:
        """Return pairings where both arms are in the active selection."""
        if active_arm_ids is None:
            return self.get_pairings()
        return [
            p.to_dict()
            for p in self.pairings
            if p.leader_id in active_arm_ids and p.follower_id in active_arm_ids
        ]

    # --- CRUD Methods ---

    def create_pairing(self, leader_id: str, follower_id: str, name: str | None = None) -> dict:
        """Create a new leader-follower pairing."""
        if leader_id not in self.arms:
            return {"success": False, "error": f"Leader arm '{leader_id}' not found"}
        if follower_id not in self.arms:
            return {"success": False, "error": f"Follower arm '{follower_id}' not found"}

        leader = self.arms[leader_id]
        follower = self.arms[follower_id]

        if leader.role != ArmRole.LEADER:
            return {"success": False, "error": f"'{leader_id}' is not a leader arm"}
        if follower.role != ArmRole.FOLLOWER:
            return {"success": False, "error": f"'{follower_id}' is not a follower arm"}

        for p in self.pairings:
            if p.leader_id == leader_id and p.follower_id == follower_id:
                return {"success": False, "error": "Pairing already exists"}

        warning = None
        if (
            leader.structural_design
            and follower.structural_design
            and leader.structural_design != follower.structural_design
        ):
            warning = (
                f"Structural mismatch: {leader.name} ({leader.structural_design}) "
                f"may not match {follower.name} ({follower.structural_design})"
            )

        pairing_name = name or f"{leader.name} -> {follower.name}"
        pairing = Pairing(leader_id=leader_id, follower_id=follower_id, name=pairing_name)
        self.pairings.append(pairing)
        self._save_config()

        return {"success": True, "warning": warning, "pairing": pairing.to_dict()}

    def remove_pairing(self, leader_id: str, follower_id: str) -> dict:
        """Remove an existing pairing."""
        for i, p in enumerate(self.pairings):
            if p.leader_id == leader_id and p.follower_id == follower_id:
                self.pairings.pop(i)
                self._save_config()
                return {"success": True}
        return {"success": False, "error": "Pairing not found"}

    def add_arm(self, arm_data: dict) -> dict:
        """Add a new arm to the registry."""
        arm_id = arm_data.get("id")
        if not arm_id:
            return {"success": False, "error": "Arm ID is required"}
        if arm_id in self.arms:
            return {"success": False, "error": f"Arm '{arm_id}' already exists"}

        try:
            arm = ArmDefinition(
                id=arm_id,
                name=arm_data.get("name", arm_id),
                role=ArmRole(arm_data.get("role", "follower")),
                motor_type=MotorType(arm_data.get("motor_type", "sts3215")),
                port=arm_data.get("port", ""),
                enabled=arm_data.get("enabled", True),
                structural_design=arm_data.get("structural_design"),
                config=arm_data.get("config", {}),
            )
            self.arms[arm_id] = arm
            self.arm_status[arm_id] = ConnectionStatus.DISCONNECTED
            self._save_config()
            return {"success": True, "arm": arm.to_dict()}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def update_arm(self, arm_id: str, **kwargs: Any) -> dict:
        """Update arm properties."""
        if arm_id not in self.arms:
            return {"success": False, "error": f"Arm '{arm_id}' not found"}

        arm = self.arms[arm_id]
        if "name" in kwargs:
            arm.name = kwargs["name"]
        if "port" in kwargs:
            arm.port = kwargs["port"]
        if "enabled" in kwargs:
            arm.enabled = kwargs["enabled"]
        if "structural_design" in kwargs:
            arm.structural_design = kwargs["structural_design"]
        if "config" in kwargs:
            arm.config.update(kwargs["config"])

        self._save_config()
        return {"success": True, "arm": arm.to_dict()}

    def remove_arm(self, arm_id: str) -> dict:
        """Remove an arm from the registry."""
        if arm_id not in self.arms:
            return {"success": False, "error": f"Arm '{arm_id}' not found"}

        if self.arm_status.get(arm_id) == ConnectionStatus.CONNECTED:
            self.disconnect_arm(arm_id)

        self.pairings = [
            p for p in self.pairings if p.leader_id != arm_id and p.follower_id != arm_id
        ]
        del self.arms[arm_id]
        del self.arm_status[arm_id]
        self.arm_instances.pop(arm_id, None)

        self._save_config()
        return {"success": True}

    # --- Connection Management ---

    def connect_arm(self, arm_id: str) -> dict:
        """Connect a specific arm by creating the appropriate hardware instance."""
        if arm_id not in self.arms:
            return {"success": False, "error": f"Arm '{arm_id}' not found"}

        arm = self.arms[arm_id]
        if not arm.enabled:
            return {"success": False, "error": f"Arm '{arm_id}' is disabled"}

        self.arm_status[arm_id] = ConnectionStatus.CONNECTING

        try:
            instance = self._create_arm_instance(arm)
            if instance:
                self.arm_instances[arm_id] = instance
                self.arm_status[arm_id] = ConnectionStatus.CONNECTED
                if hasattr(instance, "is_calibrated"):
                    arm.calibrated = instance.is_calibrated
                logger.info("Connected arm: %s (%s)", arm.name, arm_id)
                return {"success": True, "status": "connected"}
            else:
                self.arm_status[arm_id] = ConnectionStatus.ERROR
                return {"success": False, "error": "Failed to create arm instance"}
        except Exception as e:
            self.arm_status[arm_id] = ConnectionStatus.ERROR
            logger.error("Failed to connect arm %s: %s", arm_id, e)
            return {"success": False, "error": str(e)}

    def disconnect_arm(self, arm_id: str) -> dict:
        """Disconnect a specific arm."""
        if arm_id not in self.arms:
            return {"success": False, "error": f"Arm '{arm_id}' not found"}

        if arm_id in self.arm_instances:
            try:
                instance = self.arm_instances[arm_id]
                if hasattr(instance, "disconnect"):
                    instance.disconnect()
                del self.arm_instances[arm_id]
            except Exception as e:
                logger.error("Error disconnecting arm %s: %s", arm_id, e)

        self.arm_status[arm_id] = ConnectionStatus.DISCONNECTED
        logger.info("Disconnected arm: %s", arm_id)
        return {"success": True, "status": "disconnected"}

    def _create_arm_instance(self, arm: ArmDefinition) -> Any:
        """Create the appropriate robot/teleoperator instance.

        Factory method that imports and instantiates lerobot hardware
        classes based on motor type and role. Imports are lazy to avoid
        hard dependency on lerobot when not connecting.

        Raises:
            HardwareError: If lerobot is not importable when connecting.
        """
        _lerobot_hint = (
            "lerobot not found. Ensure lerobot/src is on PYTHONPATH. "
            "See start.sh or run with PYTHONPATH=lerobot/src:$PYTHONPATH"
        )

        if arm.motor_type == MotorType.STS3215:
            if arm.role == ArmRole.FOLLOWER:
                try:
                    from lerobot.robots.umbra_follower import UmbraFollowerRobot
                    from lerobot.robots.umbra_follower.config_umbra_follower import (
                        UmbraFollowerConfig,
                    )
                except ImportError as e:
                    raise HardwareError(f"{_lerobot_hint} ({e})") from e

                config = UmbraFollowerConfig(id=arm.id, port=arm.port, cameras={})
                robot = UmbraFollowerRobot(config)
                robot.connect(calibrate=False)
                return robot
            else:
                try:
                    from lerobot.teleoperators.umbra_leader import UmbraLeaderRobot
                    from lerobot.teleoperators.umbra_leader.config_umbra_leader import (
                        UmbraLeaderConfig,
                    )
                except ImportError as e:
                    raise HardwareError(f"{_lerobot_hint} ({e})") from e

                config = UmbraLeaderConfig(id=arm.id, port=arm.port)
                leader = UmbraLeaderRobot(config)
                leader.connect(calibrate=False)
                return leader

        elif arm.motor_type == MotorType.DAMIAO:
            if arm.role == ArmRole.FOLLOWER:
                try:
                    from lerobot.robots.damiao_follower import DamiaoFollowerRobot
                    from lerobot.robots.damiao_follower.config_damiao_follower import (
                        DamiaoFollowerConfig,
                    )
                except ImportError as e:
                    raise HardwareError(f"{_lerobot_hint} ({e})") from e

                config = DamiaoFollowerConfig(
                    id=arm.id,
                    port=arm.port,
                    velocity_limit=arm.config.get("velocity_limit", 0.3),
                    cameras={},
                )
                robot = DamiaoFollowerRobot(config)
                robot.connect()
                return robot
            else:
                logger.warning("Damiao leader arms not yet supported")
                return None

        elif arm.motor_type in (MotorType.DYNAMIXEL_XL330, MotorType.DYNAMIXEL_XL430):
            if arm.role == ArmRole.LEADER:
                try:
                    from lerobot.teleoperators.dynamixel_leader import DynamixelLeader
                    from lerobot.teleoperators.dynamixel_leader.config_dynamixel_leader import (
                        DynamixelLeaderConfig,
                    )
                except ImportError as e:
                    raise HardwareError(f"{_lerobot_hint} ({e})") from e

                config = DynamixelLeaderConfig(
                    id=arm.id,
                    port=arm.port,
                    structural_design=arm.structural_design or "",
                )
                leader = DynamixelLeader(config)
                leader.connect(calibrate=False)
                return leader
            else:
                logger.warning("Dynamixel follower arms not typical use case")
                return None

        logger.warning("Unknown motor type: %s", arm.motor_type)
        return None

    # --- Persistence ---

    def _save_config(self) -> None:
        """Save current configuration to settings.yaml."""
        arms_config: dict = {}
        for arm_id, arm in self.arms.items():
            entry: dict = {
                "name": arm.name,
                "role": arm.role.value,
                "motor_type": arm.motor_type.value,
                "port": arm.port,
                "enabled": arm.enabled,
            }
            if arm.structural_design:
                entry["structural_design"] = arm.structural_design
            if arm.config:
                entry["config"] = arm.config
            arms_config[arm_id] = entry

        pairings_config = [
            {"leader": p.leader_id, "follower": p.follower_id, "name": p.name}
            for p in self.pairings
        ]

        self._config_data["arms"] = arms_config
        self._config_data["pairings"] = pairings_config

        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, "w") as f:
                yaml.dump(self._config_data, f, default_flow_style=False, sort_keys=False)
            logger.info("Saved arm configuration to %s", self.config_path)
        except Exception as e:
            logger.error("Failed to save config: %s", e)

    # --- Home Position ---

    def set_home(self, arm_id: str) -> dict:
        """Capture current motor positions as the home position.

        Reads from the connected arm instance and stores in
        ``arm.config["home_position"]``. Persists to YAML.
        """
        if arm_id not in self.arms:
            return {"success": False, "error": f"Arm '{arm_id}' not found"}
        if self.arm_status.get(arm_id) != ConnectionStatus.CONNECTED:
            return {"success": False, "error": f"Arm '{arm_id}' not connected"}

        instance = self.arm_instances.get(arm_id)
        if instance is None:
            return {"success": False, "error": "No arm instance available"}

        try:
            # Read current positions from the hardware instance
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

            if not positions:
                return {"success": False, "error": "Could not read motor positions"}

            self.arms[arm_id].config["home_position"] = positions
            self._save_config()
            logger.info("Set home position for %s: %d motors", arm_id, len(positions))
            return {"success": True, "positions": positions}
        except Exception as exc:
            logger.error("Failed to set home for %s: %s", arm_id, exc)
            return {"success": False, "error": str(exc)}

    def clear_home(self, arm_id: str) -> dict:
        """Remove stored home position for an arm."""
        if arm_id not in self.arms:
            return {"success": False, "error": f"Arm '{arm_id}' not found"}

        self.arms[arm_id].config.pop("home_position", None)
        self._save_config()
        logger.info("Cleared home position for %s", arm_id)
        return {"success": True}

    # --- Compatibility ---

    def get_compatible_followers(self, leader_id: str) -> list[dict]:
        """Return follower arms with matching structural design."""
        if leader_id not in self.arms:
            return []
        leader = self.arms[leader_id]
        if not leader.structural_design:
            return self.get_followers()
        return [
            a
            for a in self.get_followers()
            if a.get("structural_design") == leader.structural_design
        ]

    # --- Utility ---

    def set_arm_calibrated(self, arm_id: str, calibrated: bool) -> None:
        """Update calibration status for an arm."""
        if arm_id in self.arms:
            self.arms[arm_id].calibrated = calibrated

    def get_arm_instance(self, arm_id: str) -> Any | None:
        """Get the connected robot/teleoperator instance for an arm."""
        return self.arm_instances.get(arm_id)

    def get_status_summary(self) -> dict:
        """Get a summary of all arm statuses."""
        connected = sum(1 for s in self.arm_status.values() if s == ConnectionStatus.CONNECTED)
        return {
            "total_arms": len(self.arms),
            "connected": connected,
            "disconnected": len(self.arms) - connected,
            "leaders": len([a for a in self.arms.values() if a.role == ArmRole.LEADER]),
            "followers": len([a for a in self.arms.values() if a.role == ArmRole.FOLLOWER]),
            "pairings": len(self.pairings),
        }
