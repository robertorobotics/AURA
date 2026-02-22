"""Motor diagnostics — read position, temperature, current, errors from arms.

Dispatches to protocol-specific readers based on ``MotorType``.
Returns partial data on read failures rather than raising.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from nextis.hardware.types import MotorType

logger = logging.getLogger(__name__)


@dataclass
class MotorDiagnostics:
    """Diagnostic data for a single motor."""

    motor_id: int
    name: str
    position: float | None = None
    velocity: float | None = None
    temperature_c: float | None = None
    current_ma: float | None = None
    voltage_v: float | None = None
    error_flags: int = 0
    error_description: str = ""

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "motor_id": self.motor_id,
            "name": self.name,
            "position": self.position,
            "velocity": self.velocity,
            "temperature_c": self.temperature_c,
            "current_ma": self.current_ma,
            "voltage_v": self.voltage_v,
            "error_flags": self.error_flags,
            "error_description": self.error_description,
        }


def read_diagnostics(instance: Any, motor_type: MotorType) -> list[MotorDiagnostics]:
    """Read diagnostics from all motors on a connected arm.

    Args:
        instance: Connected robot/teleoperator hardware instance.
        motor_type: Type of motors in this arm.

    Returns:
        List of per-motor diagnostics. Empty if instance is None or
        if the motor type is unsupported.
    """
    if instance is None:
        return []

    try:
        if motor_type == MotorType.STS3215:
            return _read_feetech(instance)
        if motor_type in (MotorType.DYNAMIXEL_XL330, MotorType.DYNAMIXEL_XL430):
            return _read_dynamixel(instance)
        if motor_type == MotorType.DAMIAO:
            return _read_damiao(instance)
    except Exception as exc:
        logger.error("Diagnostics read failed for %s: %s", motor_type.value, exc)

    return []


def _read_feetech(instance: Any) -> list[MotorDiagnostics]:
    """Read diagnostics from Feetech STS3215 bus.

    Expects ``instance.bus`` with ``sync_read`` or ``read`` methods.
    """
    results: list[MotorDiagnostics] = []
    bus = getattr(instance, "bus", None)
    if bus is None:
        return results

    motor_names = getattr(instance, "motor_names", getattr(bus, "motor_names", []))
    motor_ids = getattr(bus, "motor_ids", [])

    for i, name in enumerate(motor_names):
        mid = motor_ids[i] if i < len(motor_ids) else i
        diag = MotorDiagnostics(motor_id=mid, name=name)
        try:
            pos = _safe_read(bus, "Present_Position", name)
            diag.position = pos
            diag.velocity = _safe_read(bus, "Present_Speed", name)
            diag.temperature_c = _safe_read(bus, "Present_Temperature", name)
            diag.current_ma = _safe_read(bus, "Present_Current", name)
            diag.voltage_v = _safe_read(bus, "Present_Voltage", name)
        except Exception as exc:
            logger.debug("Feetech read error for motor %s: %s", name, exc)
        results.append(diag)

    return results


def _read_dynamixel(instance: Any) -> list[MotorDiagnostics]:
    """Read diagnostics from Dynamixel bus.

    Expects ``instance.bus`` with Dynamixel SDK-style read methods.
    """
    results: list[MotorDiagnostics] = []
    bus = getattr(instance, "bus", None)
    if bus is None:
        return results

    motor_names = getattr(instance, "motor_names", getattr(bus, "motor_names", []))
    motor_ids = getattr(bus, "motor_ids", [])

    for i, name in enumerate(motor_names):
        mid = motor_ids[i] if i < len(motor_ids) else i
        diag = MotorDiagnostics(motor_id=mid, name=name)
        try:
            diag.position = _safe_read(bus, "Present_Position", name)
            diag.velocity = _safe_read(bus, "Present_Velocity", name)
            diag.temperature_c = _safe_read(bus, "Present_Temperature", name)
            diag.current_ma = _safe_read(bus, "Present_Current", name)
            diag.voltage_v = _safe_read(bus, "Present_Input_Voltage", name)
            hw_error = _safe_read(bus, "Hardware_Error_Status", name)
            if hw_error is not None:
                diag.error_flags = int(hw_error)
                diag.error_description = _decode_dxl_errors(diag.error_flags)
        except Exception as exc:
            logger.debug("Dynamixel read error for motor %s: %s", name, exc)
        results.append(diag)

    return results


def _read_damiao(instance: Any) -> list[MotorDiagnostics]:
    """Read diagnostics from Damiao CAN bus.

    Expects ``instance.motors`` dict with motor state attributes.
    """
    results: list[MotorDiagnostics] = []
    motors = getattr(instance, "motors", {})
    if not motors:
        # Try alternate attribute names
        motor_states = getattr(instance, "motor_states", {})
        if not motor_states:
            return results
        motors = motor_states

    for name, motor in motors.items():
        mid = getattr(motor, "id", 0)
        diag = MotorDiagnostics(
            motor_id=mid,
            name=name,
            position=getattr(motor, "position", None),
            velocity=getattr(motor, "velocity", None),
            temperature_c=getattr(motor, "temperature", None),
            current_ma=getattr(motor, "current", None),
        )
        error = getattr(motor, "error", 0)
        if error:
            diag.error_flags = int(error)
            diag.error_description = f"Motor error code: {error}"
        results.append(diag)

    return results


def _safe_read(bus: Any, register: str, motor_name: str) -> float | None:
    """Attempt to read a single register from the bus.

    Returns ``None`` on any failure instead of raising.
    """
    try:
        if hasattr(bus, "read"):
            val = bus.read(register, motor_name)
            return float(val) if val is not None else None
        if hasattr(bus, "sync_read"):
            vals = bus.sync_read(register, [motor_name])
            if vals and motor_name in vals:
                return float(vals[motor_name])
    except Exception:
        pass
    return None


def _decode_dxl_errors(flags: int) -> str:
    """Decode Dynamixel hardware error status register."""
    errors: list[str] = []
    if flags & 0x01:
        errors.append("input_voltage")
    if flags & 0x04:
        errors.append("overheating")
    if flags & 0x08:
        errors.append("motor_encoder")
    if flags & 0x10:
        errors.append("electrical_shock")
    if flags & 0x20:
        errors.append("overload")
    return ", ".join(errors) if errors else ""
