"""Serial port and motor scanning for hardware discovery.

Provides ``scan_ports()`` for enumerating serial/CAN devices and
``scan_motors()`` for probing motor IDs at various baud rates.
Port scanning is a separate concern from the registry (which only
manages known arms).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from nextis.hardware.types import MotorType

logger = logging.getLogger(__name__)

# Default baud rates to try per motor type
_DEFAULT_BAUDS: dict[MotorType, list[int]] = {
    MotorType.STS3215: [1_000_000],
    MotorType.DAMIAO: [1_000_000],
    MotorType.DYNAMIXEL_XL330: [57_600, 1_000_000],
    MotorType.DYNAMIXEL_XL430: [57_600, 1_000_000],
}

# Max motor ID to probe (keep scan fast)
_MAX_SCAN_ID = 20


@dataclass
class PortInfo:
    """A discovered serial or CAN port."""

    port: str
    description: str
    hardware_id: str
    in_use: bool = False


@dataclass
class DiscoveredMotor:
    """A motor found during a scan."""

    motor_id: int
    motor_type: str
    baud_rate: int
    model_number: int | None = None


def scan_ports(configured_ports: set[str] | None = None) -> list[PortInfo]:
    """List available serial ports using pyserial.

    Args:
        configured_ports: Ports already assigned to arms (marked ``in_use``).

    Returns:
        List of discovered ports. Empty if pyserial is not installed.
    """
    try:
        from serial.tools.list_ports import comports
    except ImportError:
        logger.warning("pyserial not installed — port scanning unavailable")
        return []

    configured = configured_ports or set()
    results: list[PortInfo] = []

    try:
        for port_info in comports():
            results.append(
                PortInfo(
                    port=port_info.device,
                    description=port_info.description or "",
                    hardware_id=port_info.hwid or "",
                    in_use=port_info.device in configured,
                )
            )
    except OSError as exc:
        logger.error("Error enumerating serial ports: %s", exc)

    in_use_count = sum(1 for p in results if p.in_use)
    logger.info("Port scan: found %d ports (%d in use)", len(results), in_use_count)
    return results


def scan_motors(
    port: str,
    motor_type: MotorType,
    baud_rates: list[int] | None = None,
) -> list[DiscoveredMotor]:
    """Scan a serial port for motors at one or more baud rates.

    Args:
        port: Serial port path (e.g. ``/dev/ttyUSB0``).
        motor_type: Type of motor to scan for.
        baud_rates: Baud rates to try. Defaults per motor type.

    Returns:
        List of discovered motors. Empty on error or if no motors found.
    """
    rates = baud_rates or _DEFAULT_BAUDS.get(motor_type, [1_000_000])
    results: list[DiscoveredMotor] = []

    for baud in rates:
        try:
            if motor_type in (MotorType.DYNAMIXEL_XL330, MotorType.DYNAMIXEL_XL430):
                results.extend(_scan_dynamixel(port, baud, motor_type))
            elif motor_type == MotorType.STS3215:
                results.extend(_scan_feetech(port, baud))
            elif motor_type == MotorType.DAMIAO:
                results.extend(_scan_damiao(port))
                break  # CAN doesn't use baud rates the same way
        except PermissionError:
            logger.error("Permission denied accessing %s", port)
            break
        except OSError as exc:
            logger.error("Error scanning %s at %d baud: %s", port, baud, exc)

    # Deduplicate by motor_id
    seen: set[int] = set()
    unique: list[DiscoveredMotor] = []
    for m in results:
        if m.motor_id not in seen:
            seen.add(m.motor_id)
            unique.append(m)

    logger.info("Motor scan on %s: found %d motors", port, len(unique))
    return unique


def _scan_dynamixel(port: str, baud_rate: int, motor_type: MotorType) -> list[DiscoveredMotor]:
    """Ping Dynamixel motors using Protocol 2.0."""
    try:
        import serial
    except ImportError:
        return []

    found: list[DiscoveredMotor] = []
    try:
        with serial.Serial(port, baud_rate, timeout=0.02) as ser:
            for motor_id in range(_MAX_SCAN_ID + 1):
                # Dynamixel Protocol 2.0 ping packet
                packet = _build_dxl2_ping(motor_id)
                ser.reset_input_buffer()
                ser.write(packet)
                response = ser.read(20)
                if len(response) >= 11 and response[4] == motor_id:
                    model = (
                        int.from_bytes(response[9:11], "little") if len(response) >= 13 else None
                    )
                    found.append(
                        DiscoveredMotor(
                            motor_id=motor_id,
                            motor_type=motor_type.value,
                            baud_rate=baud_rate,
                            model_number=model,
                        )
                    )
    except (serial.SerialException, OSError) as exc:
        logger.debug("Dynamixel scan error on %s: %s", port, exc)

    return found


def _build_dxl2_ping(motor_id: int) -> bytes:
    """Build a Dynamixel Protocol 2.0 ping instruction packet."""
    # Header: FF FF FD 00, ID, LEN_L, LEN_H, INST(0x01)
    header = bytes([0xFF, 0xFF, 0xFD, 0x00])
    length = 3  # instruction(1) + CRC(2)
    packet_body = bytes([motor_id, length & 0xFF, (length >> 8) & 0xFF, 0x01])
    full = header + packet_body
    crc = _crc16_dxl(full)
    return full + bytes([crc & 0xFF, (crc >> 8) & 0xFF])


def _crc16_dxl(data: bytes) -> int:
    """Compute Dynamixel CRC-16 checksum."""
    crc_table = [
        0x0000,
        0x8005,
        0x800F,
        0x000A,
        0x801B,
        0x001E,
        0x0014,
        0x8011,
        0x8033,
        0x0036,
        0x003C,
        0x8039,
        0x0028,
        0x802D,
        0x8027,
        0x0022,
        0x8063,
        0x0066,
        0x006C,
        0x8069,
        0x0078,
        0x807D,
        0x8077,
        0x0072,
        0x0050,
        0x8055,
        0x805F,
        0x005A,
        0x804B,
        0x004E,
        0x0044,
        0x8041,
        0x80C3,
        0x00C6,
        0x00CC,
        0x80C9,
        0x00D8,
        0x80DD,
        0x80D7,
        0x00D2,
        0x00F0,
        0x80F5,
        0x80FF,
        0x00FA,
        0x80EB,
        0x00EE,
        0x00E4,
        0x80E1,
        0x00A0,
        0x80A5,
        0x80AF,
        0x00AA,
        0x80BB,
        0x00BE,
        0x00B4,
        0x80B1,
        0x8093,
        0x0096,
        0x009C,
        0x8099,
        0x0088,
        0x808D,
        0x8087,
        0x0082,
    ]
    crc = 0
    for byte in data:
        i = ((crc >> 8) ^ byte) & 0xFF
        crc = ((crc << 8) ^ crc_table[i >> 2]) & 0xFFFF
    return crc


def _scan_feetech(port: str, baud_rate: int) -> list[DiscoveredMotor]:
    """Ping Feetech STS3215 motors."""
    try:
        import serial
    except ImportError:
        return []

    found: list[DiscoveredMotor] = []
    try:
        with serial.Serial(port, baud_rate, timeout=0.02) as ser:
            for motor_id in range(_MAX_SCAN_ID + 1):
                # Feetech protocol: FF FF ID LEN INST(0x01) CHECKSUM
                length = 2  # instruction + checksum
                checksum = (~(motor_id + length + 0x01)) & 0xFF
                packet = bytes([0xFF, 0xFF, motor_id, length, 0x01, checksum])
                ser.reset_input_buffer()
                ser.write(packet)
                response = ser.read(10)
                if len(response) >= 6 and response[0] == 0xFF and response[1] == 0xFF:
                    resp_id = response[2]
                    if resp_id == motor_id:
                        found.append(
                            DiscoveredMotor(
                                motor_id=motor_id,
                                motor_type=MotorType.STS3215.value,
                                baud_rate=baud_rate,
                            )
                        )
    except (serial.SerialException, OSError) as exc:
        logger.debug("Feetech scan error on %s: %s", port, exc)

    return found


def _scan_damiao(port: str) -> list[DiscoveredMotor]:
    """Scan Damiao CAN bus for motor IDs.

    Uses SocketCAN if available, otherwise tries serial CAN bridge.
    """
    found: list[DiscoveredMotor] = []

    # Try SocketCAN first
    try:
        import socket as sock

        s = sock.socket(sock.AF_CAN, sock.SOCK_RAW, sock.CAN_RAW)
        s.settimeout(0.1)
        try:
            s.bind((port,))
            # Send broadcast query and collect responses
            for motor_id in range(_MAX_SCAN_ID + 1):
                # Damiao enable command: CAN ID = motor_id, data = enable frame
                can_id = motor_id
                data = bytes([0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFC])
                frame = can_id.to_bytes(4, "little") + len(data).to_bytes(4, "little") + data
                try:
                    s.send(frame)
                    resp = s.recv(16)
                    if resp:
                        found.append(
                            DiscoveredMotor(
                                motor_id=motor_id,
                                motor_type=MotorType.DAMIAO.value,
                                baud_rate=1_000_000,
                            )
                        )
                except (OSError, TimeoutError):
                    continue
        finally:
            s.close()
    except (OSError, AttributeError):
        logger.debug("SocketCAN not available for %s — skipping Damiao scan", port)

    return found
