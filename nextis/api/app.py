"""AURA API — thin FastAPI layer for the Nextis Assembler.

All business logic lives in the nextis package. This module only wires
routes, middleware, and the application lifecycle.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from nextis.api.routes import (
    analytics,
    assembly,
    execution,
    hardware,
    homing,
    recording,
    teleop,
    training,
)

logger = logging.getLogger(__name__)

app = FastAPI(title="AURA API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(assembly.router, prefix="/assemblies", tags=["assemblies"])
app.include_router(execution.router, prefix="/execution", tags=["execution"])
app.include_router(analytics.router, prefix="/analytics", tags=["analytics"])
app.include_router(teleop.router, prefix="/teleop", tags=["teleop"])
app.include_router(recording.router, prefix="/recording", tags=["recording"])
app.include_router(training.router, prefix="/training", tags=["training"])
app.include_router(hardware.router, prefix="/hardware", tags=["hardware"])
app.include_router(homing.router, prefix="/homing", tags=["homing"])

# Serve GLB mesh files for the 3D assembly viewer
_MESHES_DIR = Path(__file__).resolve().parents[2] / "data" / "meshes"
_MESHES_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/meshes", StaticFiles(directory=str(_MESHES_DIR)), name="meshes")


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}


@app.get("/system/info")
async def system_info() -> dict:
    """System information for the frontend demo banner."""
    configs_dir = Path(__file__).resolve().parents[2] / "configs" / "assemblies"

    lerobot_available = False
    try:
        import lerobot  # noqa: F401

        lerobot_available = True
    except ImportError:
        pass

    mode = "mock"
    try:
        summary = hardware.get_registry().get_status_summary()
        if summary["connected"] > 0:
            mode = "hardware"
    except Exception:
        pass

    return {
        "version": "0.1.0",
        "mode": mode,
        "assemblies": len(list(configs_dir.glob("*.json"))),
        "lerobotAvailable": lerobot_available,
    }
