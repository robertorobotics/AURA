"""ToolRegistryService — CRUD, connection, and activation for tools and triggers.

Mirrors the pattern of ``ArmRegistryService`` but for simpler single-motor
end-effector tools (screwdrivers, grippers) and trigger devices (buttons,
foot pedals).

Config is read from/written to the ``tools``, ``triggers``, and
``tool_pairings`` sections of ``settings.yaml``.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

import yaml

from nextis.tools.types import (
    ToolDefinition,
    ToolPairing,
    ToolStatus,
    ToolType,
    TriggerDefinition,
    TriggerType,
)

logger = logging.getLogger(__name__)


class ToolRegistryService:
    """Central service for tool and trigger management.

    Args:
        config_data: Parsed settings.yaml dict (full config).
        config_path: Path to settings.yaml for persistence.
    """

    def __init__(self, config_data: dict, config_path: str | Path) -> None:
        self.tools: dict[str, ToolDefinition] = {}
        self.triggers: dict[str, TriggerDefinition] = {}
        self.pairings: list[ToolPairing] = []

        self.tool_status: dict[str, ToolStatus] = {}
        self.trigger_status: dict[str, ToolStatus] = {}
        self.tool_instances: dict[str, Any] = {}
        self.trigger_instances: dict[str, Any] = {}

        self._lock = threading.Lock()
        self._config_path = Path(config_path)
        self._config_data = config_data

        self._load_config()

    # --- Config Loading ---

    def _load_config(self) -> None:
        """Load tools, triggers, and pairings from config data."""
        for tool_id, cfg in (self._config_data.get("tools") or {}).items():
            try:
                tool = ToolDefinition(
                    id=tool_id,
                    name=cfg.get("name", tool_id),
                    motor_type=cfg.get("motor_type", "sts3215"),
                    port=cfg.get("port", ""),
                    motor_id=cfg.get("motor_id", 0),
                    tool_type=ToolType(cfg.get("tool_type", "custom")),
                    enabled=cfg.get("enabled", True),
                    config=cfg.get("config", {}),
                )
                self.tools[tool_id] = tool
                self.tool_status[tool_id] = ToolStatus.DISCONNECTED
                logger.info("Loaded tool: %s (%s)", tool.name, tool_id)
            except Exception as exc:
                logger.error("Failed to load tool %s: %s", tool_id, exc)

        for trig_id, cfg in (self._config_data.get("triggers") or {}).items():
            try:
                trigger = TriggerDefinition(
                    id=trig_id,
                    name=cfg.get("name", trig_id),
                    trigger_type=TriggerType(cfg.get("trigger_type", "gpio_switch")),
                    port=cfg.get("port", ""),
                    pin=cfg.get("pin", 0),
                    active_low=cfg.get("active_low", True),
                    enabled=cfg.get("enabled", True),
                )
                self.triggers[trig_id] = trigger
                self.trigger_status[trig_id] = ToolStatus.DISCONNECTED
                logger.info("Loaded trigger: %s (%s)", trigger.name, trig_id)
            except Exception as exc:
                logger.error("Failed to load trigger %s: %s", trig_id, exc)

        for cfg in self._config_data.get("tool_pairings") or []:
            try:
                pairing = ToolPairing(
                    trigger_id=cfg["trigger_id"],
                    tool_id=cfg["tool_id"],
                    name=cfg.get("name", f"{cfg['trigger_id']} -> {cfg['tool_id']}"),
                    action=cfg.get("action", "toggle"),
                )
                self.pairings.append(pairing)
            except Exception as exc:
                logger.error("Failed to load tool pairing: %s", exc)

    # --- Tool CRUD ---

    def get_all_tools(self) -> list[dict]:
        """Return all tools with their current status."""
        result = []
        for tool_id, tool in self.tools.items():
            d = tool.to_dict()
            d["status"] = self.tool_status.get(tool_id, ToolStatus.DISCONNECTED).value
            result.append(d)
        return result

    def get_tool(self, tool_id: str) -> dict | None:
        """Get a specific tool by ID."""
        if tool_id not in self.tools:
            return None
        d = self.tools[tool_id].to_dict()
        d["status"] = self.tool_status.get(tool_id, ToolStatus.DISCONNECTED).value
        return d

    def add_tool(self, tool_data: dict) -> dict:
        """Add a new tool to the registry."""
        tool_id = tool_data.get("id")
        if not tool_id:
            return {"success": False, "error": "Tool ID is required"}
        if tool_id in self.tools:
            return {"success": False, "error": f"Tool '{tool_id}' already exists"}

        try:
            tool = ToolDefinition(
                id=tool_id,
                name=tool_data.get("name", tool_id),
                motor_type=tool_data.get("motor_type", "sts3215"),
                port=tool_data.get("port", ""),
                motor_id=tool_data.get("motor_id", 0),
                tool_type=ToolType(tool_data.get("tool_type", "custom")),
                enabled=tool_data.get("enabled", True),
                config=tool_data.get("config", {}),
            )
            self.tools[tool_id] = tool
            self.tool_status[tool_id] = ToolStatus.DISCONNECTED
            self._save_config()
            return {"success": True, "tool": tool.to_dict()}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def update_tool(self, tool_id: str, **kwargs: Any) -> dict:
        """Update tool properties."""
        if tool_id not in self.tools:
            return {"success": False, "error": f"Tool '{tool_id}' not found"}

        tool = self.tools[tool_id]
        if "name" in kwargs:
            tool.name = kwargs["name"]
        if "port" in kwargs:
            tool.port = kwargs["port"]
        if "motor_id" in kwargs:
            tool.motor_id = kwargs["motor_id"]
        if "enabled" in kwargs:
            tool.enabled = kwargs["enabled"]
        if "config" in kwargs:
            tool.config.update(kwargs["config"])

        self._save_config()
        return {"success": True, "tool": tool.to_dict()}

    def remove_tool(self, tool_id: str) -> dict:
        """Remove a tool from the registry."""
        if tool_id not in self.tools:
            return {"success": False, "error": f"Tool '{tool_id}' not found"}

        if self.tool_status.get(tool_id) in (ToolStatus.CONNECTED, ToolStatus.ACTIVE):
            self.disconnect_tool(tool_id)

        # Remove any pairings referencing this tool
        self.pairings = [p for p in self.pairings if p.tool_id != tool_id]
        del self.tools[tool_id]
        del self.tool_status[tool_id]
        self.tool_instances.pop(tool_id, None)

        self._save_config()
        return {"success": True}

    # --- Trigger CRUD ---

    def get_all_triggers(self) -> list[dict]:
        """Return all triggers with their current status."""
        result = []
        for trig_id, trigger in self.triggers.items():
            d = trigger.to_dict()
            d["status"] = self.trigger_status.get(trig_id, ToolStatus.DISCONNECTED).value
            result.append(d)
        return result

    def get_trigger(self, trigger_id: str) -> dict | None:
        """Get a specific trigger by ID."""
        if trigger_id not in self.triggers:
            return None
        d = self.triggers[trigger_id].to_dict()
        d["status"] = self.trigger_status.get(trigger_id, ToolStatus.DISCONNECTED).value
        return d

    def add_trigger(self, trigger_data: dict) -> dict:
        """Add a new trigger device to the registry."""
        trigger_id = trigger_data.get("id")
        if not trigger_id:
            return {"success": False, "error": "Trigger ID is required"}
        if trigger_id in self.triggers:
            return {"success": False, "error": f"Trigger '{trigger_id}' already exists"}

        try:
            trigger = TriggerDefinition(
                id=trigger_id,
                name=trigger_data.get("name", trigger_id),
                trigger_type=TriggerType(trigger_data.get("trigger_type", "gpio_switch")),
                port=trigger_data.get("port", ""),
                pin=trigger_data.get("pin", 0),
                active_low=trigger_data.get("active_low", True),
                enabled=trigger_data.get("enabled", True),
            )
            self.triggers[trigger_id] = trigger
            self.trigger_status[trigger_id] = ToolStatus.DISCONNECTED
            self._save_config()
            return {"success": True, "trigger": trigger.to_dict()}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def update_trigger(self, trigger_id: str, **kwargs: Any) -> dict:
        """Update trigger properties."""
        if trigger_id not in self.triggers:
            return {"success": False, "error": f"Trigger '{trigger_id}' not found"}

        trigger = self.triggers[trigger_id]
        if "name" in kwargs:
            trigger.name = kwargs["name"]
        if "port" in kwargs:
            trigger.port = kwargs["port"]
        if "pin" in kwargs:
            trigger.pin = kwargs["pin"]
        if "active_low" in kwargs:
            trigger.active_low = kwargs["active_low"]
        if "enabled" in kwargs:
            trigger.enabled = kwargs["enabled"]

        self._save_config()
        return {"success": True, "trigger": trigger.to_dict()}

    def remove_trigger(self, trigger_id: str) -> dict:
        """Remove a trigger from the registry."""
        if trigger_id not in self.triggers:
            return {"success": False, "error": f"Trigger '{trigger_id}' not found"}

        if self.trigger_status.get(trigger_id) == ToolStatus.CONNECTED:
            self.disconnect_trigger(trigger_id)

        # Remove any pairings referencing this trigger
        self.pairings = [p for p in self.pairings if p.trigger_id != trigger_id]
        del self.triggers[trigger_id]
        del self.trigger_status[trigger_id]
        self.trigger_instances.pop(trigger_id, None)

        self._save_config()
        return {"success": True}

    # --- Pairing CRUD ---

    def get_pairings(self) -> list[dict]:
        """Return all tool-trigger pairings."""
        return [p.to_dict() for p in self.pairings]

    def create_pairing(
        self,
        trigger_id: str,
        tool_id: str,
        name: str | None = None,
        action: str = "toggle",
    ) -> dict:
        """Create a trigger-to-tool pairing."""
        if trigger_id not in self.triggers:
            return {"success": False, "error": f"Trigger '{trigger_id}' not found"}
        if tool_id not in self.tools:
            return {"success": False, "error": f"Tool '{tool_id}' not found"}

        for p in self.pairings:
            if p.trigger_id == trigger_id and p.tool_id == tool_id:
                return {"success": False, "error": "Pairing already exists"}

        pairing_name = name or f"{self.triggers[trigger_id].name} -> {self.tools[tool_id].name}"
        pairing = ToolPairing(
            trigger_id=trigger_id,
            tool_id=tool_id,
            name=pairing_name,
            action=action,
        )
        self.pairings.append(pairing)
        self._save_config()
        return {"success": True, "pairing": pairing.to_dict()}

    def remove_pairing(self, trigger_id: str, tool_id: str) -> dict:
        """Remove a tool-trigger pairing."""
        for i, p in enumerate(self.pairings):
            if p.trigger_id == trigger_id and p.tool_id == tool_id:
                self.pairings.pop(i)
                self._save_config()
                return {"success": True}
        return {"success": False, "error": "Pairing not found"}

    # --- Connection ---

    def connect_tool(self, tool_id: str) -> dict:
        """Connect a tool's motor bus."""
        if tool_id not in self.tools:
            return {"success": False, "error": f"Tool '{tool_id}' not found"}

        tool = self.tools[tool_id]
        if not tool.enabled:
            return {"success": False, "error": f"Tool '{tool_id}' is disabled"}

        self.tool_status[tool_id] = ToolStatus.CONNECTING
        try:
            instance = self._create_tool_instance(tool)
            if instance is not None:
                self.tool_instances[tool_id] = instance
                self.tool_status[tool_id] = ToolStatus.CONNECTED
                logger.info("Connected tool: %s (%s)", tool.name, tool_id)
                return {"success": True, "status": "connected"}
            self.tool_status[tool_id] = ToolStatus.ERROR
            return {"success": False, "error": "Failed to create tool instance"}
        except Exception as exc:
            self.tool_status[tool_id] = ToolStatus.ERROR
            logger.error("Failed to connect tool %s: %s", tool_id, exc)
            return {"success": False, "error": str(exc)}

    def disconnect_tool(self, tool_id: str) -> dict:
        """Disconnect a tool."""
        if tool_id not in self.tools:
            return {"success": False, "error": f"Tool '{tool_id}' not found"}

        if tool_id in self.tool_instances:
            try:
                instance = self.tool_instances[tool_id]
                if hasattr(instance, "close"):
                    instance.close()
                del self.tool_instances[tool_id]
            except Exception as exc:
                logger.error("Error disconnecting tool %s: %s", tool_id, exc)

        self.tool_status[tool_id] = ToolStatus.DISCONNECTED
        return {"success": True, "status": "disconnected"}

    def connect_trigger(self, trigger_id: str) -> dict:
        """Connect a trigger device."""
        if trigger_id not in self.triggers:
            return {"success": False, "error": f"Trigger '{trigger_id}' not found"}

        trigger = self.triggers[trigger_id]
        if not trigger.enabled:
            return {"success": False, "error": f"Trigger '{trigger_id}' is disabled"}

        # Trigger connection is device-specific (GPIO, USB HID, etc.)
        # For now, mark as connected — actual polling starts when tool pairing is active
        self.trigger_status[trigger_id] = ToolStatus.CONNECTED
        logger.info("Connected trigger: %s (%s)", trigger.name, trigger_id)
        return {"success": True, "status": "connected"}

    def disconnect_trigger(self, trigger_id: str) -> dict:
        """Disconnect a trigger device."""
        if trigger_id not in self.triggers:
            return {"success": False, "error": f"Trigger '{trigger_id}' not found"}

        if trigger_id in self.trigger_instances:
            try:
                instance = self.trigger_instances[trigger_id]
                if hasattr(instance, "close"):
                    instance.close()
                del self.trigger_instances[trigger_id]
            except Exception as exc:
                logger.error("Error disconnecting trigger %s: %s", trigger_id, exc)

        self.trigger_status[trigger_id] = ToolStatus.DISCONNECTED
        return {"success": True, "status": "disconnected"}

    # --- Activation ---

    def activate_tool(self, tool_id: str) -> dict:
        """Start a tool (e.g. spin screwdriver)."""
        if tool_id not in self.tools:
            return {"success": False, "error": f"Tool '{tool_id}' not found"}
        if self.tool_status.get(tool_id) not in (ToolStatus.CONNECTED, ToolStatus.ACTIVE):
            return {"success": False, "error": f"Tool '{tool_id}' not connected"}

        instance = self.tool_instances.get(tool_id)
        if instance is not None and hasattr(instance, "write"):
            try:
                tool = self.tools[tool_id]
                speed = tool.config.get("speed", 500)
                direction = tool.config.get("direction", 1)
                instance.write(speed * direction)
            except Exception as exc:
                logger.error("Failed to activate tool %s: %s", tool_id, exc)
                return {"success": False, "error": str(exc)}

        self.tool_status[tool_id] = ToolStatus.ACTIVE
        logger.info("Activated tool: %s", tool_id)
        return {"success": True, "status": "active"}

    def deactivate_tool(self, tool_id: str) -> dict:
        """Stop a tool."""
        if tool_id not in self.tools:
            return {"success": False, "error": f"Tool '{tool_id}' not found"}

        instance = self.tool_instances.get(tool_id)
        if instance is not None and hasattr(instance, "write"):
            try:
                instance.write(0)
            except Exception as exc:
                logger.error("Failed to deactivate tool %s: %s", tool_id, exc)

        if self.tool_status.get(tool_id) == ToolStatus.ACTIVE:
            self.tool_status[tool_id] = ToolStatus.CONNECTED
        logger.info("Deactivated tool: %s", tool_id)
        return {"success": True, "status": "connected"}

    def toggle_tool(self, tool_id: str) -> dict:
        """Toggle a tool between active and connected states."""
        if self.tool_status.get(tool_id) == ToolStatus.ACTIVE:
            return self.deactivate_tool(tool_id)
        return self.activate_tool(tool_id)

    # --- Persistence ---

    def _save_config(self) -> None:
        """Persist tools, triggers, and pairings to settings.yaml."""
        tools_config: dict = {}
        for tool_id, tool in self.tools.items():
            entry: dict = {
                "name": tool.name,
                "motor_type": tool.motor_type,
                "port": tool.port,
                "motor_id": tool.motor_id,
                "tool_type": tool.tool_type.value,
                "enabled": tool.enabled,
            }
            if tool.config:
                entry["config"] = tool.config
            tools_config[tool_id] = entry

        triggers_config: dict = {}
        for trig_id, trigger in self.triggers.items():
            triggers_config[trig_id] = {
                "name": trigger.name,
                "trigger_type": trigger.trigger_type.value,
                "port": trigger.port,
                "pin": trigger.pin,
                "active_low": trigger.active_low,
                "enabled": trigger.enabled,
            }

        pairings_config = [
            {
                "trigger_id": p.trigger_id,
                "tool_id": p.tool_id,
                "name": p.name,
                "action": p.action,
            }
            for p in self.pairings
        ]

        self._config_data["tools"] = tools_config
        self._config_data["triggers"] = triggers_config
        self._config_data["tool_pairings"] = pairings_config

        try:
            self._config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._config_path, "w") as f:
                yaml.dump(self._config_data, f, default_flow_style=False, sort_keys=False)
            logger.info("Saved tool configuration to %s", self._config_path)
        except Exception as exc:
            logger.error("Failed to save tool config: %s", exc)

    # --- Factory ---

    def _create_tool_instance(self, tool: ToolDefinition) -> Any:
        """Create a single-motor serial connection for a tool.

        Uses direct serial access (not lerobot) since tools are simple
        single-motor devices.
        """
        try:
            import serial
        except ImportError:
            logger.error("pyserial not installed — cannot connect tool %s", tool.id)
            return None

        try:
            ser = serial.Serial(tool.port, baudrate=1_000_000, timeout=0.1)
            logger.info(
                "Opened serial port %s for tool %s (motor ID %d)",
                tool.port,
                tool.id,
                tool.motor_id,
            )
            return ser
        except (serial.SerialException, OSError) as exc:
            logger.error("Failed to open port %s for tool %s: %s", tool.port, tool.id, exc)
            return None
