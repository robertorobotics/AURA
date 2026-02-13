"""Hardware management routes — arm status, connect, disconnect.

Owns the ArmRegistryService singleton. Other route modules (teleop,
homing) import ``get_registry()`` from here.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from nextis.api.schemas import (
    ArmStatus,
    ConnectRequest,
    HardwareStatusResponse,
    PairingInfo,
)
from nextis.hardware.arm_registry import ArmRegistryService

logger = logging.getLogger(__name__)

router = APIRouter()

# Module-level lazy singleton — created on first access.
_registry: ArmRegistryService | None = None


def get_registry() -> ArmRegistryService:
    """Return the shared ArmRegistryService singleton.

    Creates it on first call using the default config path
    (``configs/arms/settings.yaml``).
    """
    global _registry  # noqa: PLW0603
    if _registry is None:
        _registry = ArmRegistryService()
        logger.info(
            "ArmRegistry initialized: %d arms, %d pairings",
            len(_registry.arms),
            len(_registry.pairings),
        )
    return _registry


# ------------------------------------------------------------------
# Routes
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


@router.post("/connect")
async def connect_arm(request: ConnectRequest) -> dict[str, str]:
    """Connect a single arm by ID.

    Calls ``registry.connect_arm()`` which lazy-imports lerobot and
    creates the hardware instance.
    """
    reg = get_registry()
    result = reg.connect_arm(request.arm_id)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error", "Connection failed"))
    logger.info("Arm connected via API: %s", request.arm_id)
    return {"status": "connected", "armId": request.arm_id}


@router.post("/disconnect")
async def disconnect_arm(request: ConnectRequest) -> dict[str, str]:
    """Disconnect a single arm by ID.

    Calls ``instance.disconnect()`` and cleans up the registry entry.
    """
    reg = get_registry()
    result = reg.disconnect_arm(request.arm_id)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error", "Disconnect failed"))
    logger.info("Arm disconnected via API: %s", request.arm_id)
    return {"status": "disconnected", "armId": request.arm_id}
