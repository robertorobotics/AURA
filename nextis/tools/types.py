"""Tool and trigger type definitions.

Data models for end-effector tools (screwdrivers, grippers), trigger
devices (foot pedals, GPIO switches), and tool-trigger pairings.
These are pure data — no hardware communication logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ToolType(StrEnum):
    """Types of end-effector tools."""

    SCREWDRIVER = "screwdriver"
    GRIPPER = "gripper"
    VACUUM = "vacuum"
    CUSTOM = "custom"


class TriggerType(StrEnum):
    """Types of activation triggers."""

    GPIO_SWITCH = "gpio_switch"
    FOOT_PEDAL = "foot_pedal"
    SOFTWARE = "software"


class ToolStatus(StrEnum):
    """Connection/activation state of a tool or trigger."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ACTIVE = "active"  # Currently running (e.g. screwdriver spinning)
    ERROR = "error"


@dataclass
class ToolDefinition:
    """Configuration for a single end-effector tool.

    Attributes:
        id: Unique tool identifier.
        name: Human-readable name.
        motor_type: Motor protocol (reuses MotorType values from hardware.types).
        port: Serial port for the tool motor.
        motor_id: Motor ID on the bus.
        tool_type: Category of tool.
        enabled: Whether this tool is active in the system.
        config: Tool-specific settings (speed, direction, torque_limit, etc.).
    """

    id: str
    name: str
    motor_type: str
    port: str
    motor_id: int
    tool_type: ToolType = ToolType.CUSTOM
    enabled: bool = True
    config: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "name": self.name,
            "motor_type": self.motor_type,
            "port": self.port,
            "motor_id": self.motor_id,
            "tool_type": self.tool_type.value,
            "enabled": self.enabled,
            "config": self.config,
        }


@dataclass
class TriggerDefinition:
    """Configuration for a trigger device (button, foot pedal, GPIO switch).

    Attributes:
        id: Unique trigger identifier.
        name: Human-readable name.
        trigger_type: Category of trigger.
        port: Device port or path.
        pin: GPIO pin number (for GPIO triggers).
        active_low: Whether the trigger is active-low (default True).
        enabled: Whether this trigger is active in the system.
    """

    id: str
    name: str
    trigger_type: TriggerType = TriggerType.GPIO_SWITCH
    port: str = ""
    pin: int = 0
    active_low: bool = True
    enabled: bool = True

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "name": self.name,
            "trigger_type": self.trigger_type.value,
            "port": self.port,
            "pin": self.pin,
            "active_low": self.active_low,
            "enabled": self.enabled,
        }


@dataclass
class ToolPairing:
    """A trigger-to-tool binding.

    Attributes:
        trigger_id: ID of the trigger device.
        tool_id: ID of the tool to control.
        name: Human-readable pairing name.
        action: How the trigger controls the tool (toggle, hold, momentary).
    """

    trigger_id: str
    tool_id: str
    name: str
    action: str = "toggle"

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "trigger_id": self.trigger_id,
            "tool_id": self.tool_id,
            "name": self.name,
            "action": self.action,
        }
