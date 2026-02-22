"""Hardware management routes — full CRUD for arms, pairings, scanning, diagnostics.

All hardware-touching endpoints use ``def`` (not ``async def``) so FastAPI
runs them in the thread pool and avoids blocking the event loop.

**Route ordering**: static routes (``/status``, ``/scan-ports``, ``/pairings``)
are defined BEFORE parameterized routes (``/arms/{arm_id}``) to prevent
FastAPI from matching literal paths as parameters.

The ``get_registry()`` wrapper is kept for backward compatibility — other
route modules (teleop.py, homing.py) import it.
"""

from __future__ import annotations

import contextlib
import logging
import threading

from fastapi import APIRouter, HTTPException

from nextis.api.schemas import (
    AddArmRequest,
    ArmStatus,
    ConnectRequest,
    CreatePairingRequest,
    DiscoveredMotorResponse,
    HardwareStatusResponse,
    MotorDiagnosticsResponse,
    PairingInfo,
    PortInfoResponse,
    RemovePairingRequest,
    ScanMotorsRequest,
    UpdateArmRequest,
)
from nextis.hardware.arm_registry import ArmRegistryService

logger = logging.getLogger(__name__)

router = APIRouter()


def get_registry() -> ArmRegistryService:
    """Return the shared ArmRegistryService from SystemState.

    Thin wrapper for backward compatibility — teleop.py, homing.py, and
    app.py import this function.
    """
    from nextis.state import get_state

    return get_state().arm_registry


def _auto_apply_calibration(arm_id: str) -> None:
    """Auto-apply calibration profile if one exists. Non-fatal on failure."""
    try:
        from nextis.state import get_state

        cal_mgr = get_state().calibration_manager
        if arm_id in cal_mgr.list_calibrated():
            cal_mgr.load(arm_id)  # validate the profile loads cleanly
            get_registry().set_arm_calibrated(arm_id, True)
            logger.info("Auto-applied calibration for %s", arm_id)
    except Exception as exc:
        logger.warning("Could not auto-apply calibration for %s: %s", arm_id, exc)


# ------------------------------------------------------------------
# Static routes (MUST come before /arms/{arm_id} parameterized routes)
# ------------------------------------------------------------------


@router.get("/status", response_model=HardwareStatusResponse)
async def hardware_status() -> HardwareStatusResponse:
    """Return all arms, pairings, and connection summary."""
    reg = get_registry()
    arms_raw = reg.get_all_arms()
    pairings_raw = reg.get_pairings()
    summary = reg.get_status_summary()

    return HardwareStatusResponse(
        arms=[ArmStatus(**a) for a in arms_raw],
        pairings=[PairingInfo(**p) for p in pairings_raw],
        total_arms=summary["total_arms"],
        connected=summary["connected"],
        disconnected=summary["disconnected"],
        leaders=summary["leaders"],
        followers=summary["followers"],
    )


@router.get("/scan-ports")
def scan_serial_ports() -> list[PortInfoResponse]:
    """Scan for available serial ports."""
    from nextis.hardware.scanning import scan_ports

    configured = {a.port for a in get_registry().arms.values()}
    results = scan_ports(configured_ports=configured)
    return [
        PortInfoResponse(
            port=r.port,
            description=r.description,
            hardware_id=r.hardware_id,
            in_use=r.in_use,
        )
        for r in results
    ]


@router.post("/scan-motors")
def scan_motors_on_port(request: ScanMotorsRequest) -> list[DiscoveredMotorResponse]:
    """Scan a port for motors at one or more baud rates."""
    from nextis.hardware.scanning import scan_motors
    from nextis.hardware.types import MotorType

    try:
        motor_type = MotorType(request.motor_type)
    except ValueError:
        raise HTTPException(400, f"Unknown motor type: {request.motor_type}") from None

    results = scan_motors(request.port, motor_type, request.baud_rates)
    return [
        DiscoveredMotorResponse(
            motor_id=r.motor_id,
            motor_type=r.motor_type,
            baud_rate=r.baud_rate,
            model_number=r.model_number,
        )
        for r in results
    ]


@router.get("/pairings")
async def list_pairings() -> list[PairingInfo]:
    """List all leader-follower pairings."""
    return [PairingInfo(**p) for p in get_registry().get_pairings()]


@router.post("/pairings")
async def create_pairing(request: CreatePairingRequest) -> dict:
    """Create a new leader-follower pairing."""
    result = get_registry().create_pairing(request.leader_id, request.follower_id, request.name)
    if not result["success"]:
        raise HTTPException(400, result.get("error", "Failed to create pairing"))
    return result


@router.delete("/pairings")
async def remove_pairing(request: RemovePairingRequest) -> dict:
    """Remove an existing pairing."""
    result = get_registry().remove_pairing(request.leader_id, request.follower_id)
    if not result["success"]:
        raise HTTPException(404, result.get("error", "Pairing not found"))
    return result


@router.post("/estop")
async def emergency_stop() -> dict[str, str]:
    """Trigger emergency stop — cut power to all motors.

    Never raises — catches all exceptions and returns success.
    An E-STOP that errors is worse than one that silently succeeds.
    """
    logger.critical("!!! E-STOP triggered via API !!!")
    try:
        from nextis.api.routes.teleop import get_teleop_loop

        loop = get_teleop_loop()
        if loop and loop.robot:
            from nextis.control.safety import SafetyLayer

            safety = SafetyLayer(robot_lock=threading.Lock())
            with contextlib.suppress(Exception):
                safety.emergency_stop(loop.robot)
        else:
            logger.info("E-STOP: no active robot — mock/idle mode, nothing to disconnect")
    except Exception as exc:
        logger.error("E-STOP handler error (non-fatal): %s", exc)
    return {"status": "stopped"}


# ------------------------------------------------------------------
# Legacy body-based connect/disconnect (backward compat)
# ------------------------------------------------------------------


@router.post("/connect")
def connect_arm_legacy(request: ConnectRequest) -> dict[str, str]:
    """Connect a single arm by ID (legacy body-based endpoint)."""
    reg = get_registry()
    result = reg.connect_arm(request.arm_id)
    if not result["success"]:
        raise HTTPException(400, result.get("error", "Connection failed"))
    _auto_apply_calibration(request.arm_id)
    logger.info("Arm connected via API: %s", request.arm_id)
    return {"status": "connected", "armId": request.arm_id}


@router.post("/disconnect")
def disconnect_arm_legacy(request: ConnectRequest) -> dict[str, str]:
    """Disconnect a single arm by ID (legacy body-based endpoint)."""
    reg = get_registry()
    result = reg.disconnect_arm(request.arm_id)
    if not result["success"]:
        raise HTTPException(400, result.get("error", "Disconnect failed"))
    logger.info("Arm disconnected via API: %s", request.arm_id)
    return {"status": "disconnected", "armId": request.arm_id}


# ------------------------------------------------------------------
# Arm collection routes
# ------------------------------------------------------------------


@router.post("/arms")
async def add_arm(request: AddArmRequest) -> dict:
    """Add a new arm to the registry."""
    result = get_registry().add_arm(request.model_dump(by_alias=False))
    if not result["success"]:
        raise HTTPException(400, result.get("error", "Failed to add arm"))
    return result


# ------------------------------------------------------------------
# Single arm routes (parameterized — MUST come after static routes)
# ------------------------------------------------------------------


@router.get("/arms/{arm_id}")
async def get_arm(arm_id: str) -> ArmStatus:
    """Get a single arm by ID with current status."""
    arm = get_registry().get_arm(arm_id)
    if arm is None:
        raise HTTPException(404, f"Arm '{arm_id}' not found")
    return ArmStatus(**arm)


@router.put("/arms/{arm_id}")
async def update_arm(arm_id: str, request: UpdateArmRequest) -> dict:
    """Update arm properties (name, port, enabled, etc.)."""
    updates = {k: v for k, v in request.model_dump(by_alias=False).items() if v is not None}
    if not updates:
        raise HTTPException(400, "No fields to update")
    result = get_registry().update_arm(arm_id, **updates)
    if not result["success"]:
        raise HTTPException(400, result.get("error", "Update failed"))
    return result


@router.delete("/arms/{arm_id}")
async def delete_arm(arm_id: str) -> dict:
    """Remove an arm (disconnects first if connected)."""
    result = get_registry().remove_arm(arm_id)
    if not result["success"]:
        raise HTTPException(404, result.get("error", "Arm not found"))
    return result


@router.post("/arms/{arm_id}/connect")
def connect_arm(arm_id: str) -> dict:
    """Connect a single arm by path parameter."""
    reg = get_registry()
    result = reg.connect_arm(arm_id)
    if not result["success"]:
        raise HTTPException(400, result.get("error", "Connection failed"))
    _auto_apply_calibration(arm_id)
    logger.info("Arm connected via API: %s", arm_id)
    return {"status": "connected", "armId": arm_id}


@router.post("/arms/{arm_id}/disconnect")
def disconnect_arm(arm_id: str) -> dict:
    """Disconnect a single arm by path parameter."""
    reg = get_registry()
    result = reg.disconnect_arm(arm_id)
    if not result["success"]:
        raise HTTPException(400, result.get("error", "Disconnect failed"))
    logger.info("Arm disconnected via API: %s", arm_id)
    return {"status": "disconnected", "armId": arm_id}


@router.post("/arms/{arm_id}/set-home")
def set_home(arm_id: str) -> dict:
    """Capture current motor positions as the home position."""
    result = get_registry().set_home(arm_id)
    if not result["success"]:
        raise HTTPException(400, result.get("error", "Failed to set home"))
    return result


@router.delete("/arms/{arm_id}/set-home")
async def clear_home(arm_id: str) -> dict:
    """Clear stored home position for an arm."""
    result = get_registry().clear_home(arm_id)
    if not result["success"]:
        raise HTTPException(404, result.get("error", "Arm not found"))
    return result


@router.get("/arms/{arm_id}/motors")
def get_motor_diagnostics(arm_id: str) -> list[MotorDiagnosticsResponse]:
    """Read motor diagnostics (position, temp, current, errors)."""
    from nextis.hardware.diagnostics import read_diagnostics

    reg = get_registry()
    arm = reg.arms.get(arm_id)
    if arm is None:
        raise HTTPException(404, f"Arm '{arm_id}' not found")

    instance = reg.get_arm_instance(arm_id)
    if instance is None:
        return []  # Not connected — empty diagnostics, no crash

    results = read_diagnostics(instance, arm.motor_type)
    return [
        MotorDiagnosticsResponse(
            motor_id=r.motor_id,
            name=r.name,
            position=r.position,
            velocity=r.velocity,
            temperature_c=r.temperature_c,
            current_ma=r.current_ma,
            voltage_v=r.voltage_v,
            error_flags=r.error_flags,
            error_description=r.error_description,
        )
        for r in results
    ]


@router.get("/arms/{arm_id}/compatible-followers")
async def compatible_followers(arm_id: str) -> list[ArmStatus]:
    """Return follower arms with matching structural design."""
    results = get_registry().get_compatible_followers(arm_id)
    return [ArmStatus(**a) for a in results]
