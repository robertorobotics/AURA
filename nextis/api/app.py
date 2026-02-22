"""AURA API — thin FastAPI layer for the Nextis Assembler.

All business logic lives in the nextis package. This module only wires
routes, middleware, and the application lifecycle.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from nextis.api.routes import (
    analytics,
    assembly,
    calibration,
    cameras,
    datasets,
    execution,
    hardware,
    homing,
    policies,
    recording,
    rl_training,
    system,
    teleop,
    tools,
    training,
)
from nextis.config import ASSEMBLIES_DIR, MESHES_DIR

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Lifespan
# ------------------------------------------------------------------


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan — initialize on start, shutdown on exit."""
    from nextis.state import get_state

    get_state()
    logger.info("AURA API started")
    yield
    import nextis.state as state_mod

    if state_mod._state is not None:
        state_mod._state.shutdown()
    logger.info("AURA API stopped")


app = FastAPI(title="AURA API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(assembly.router, prefix="/assemblies", tags=["assemblies"])
app.include_router(cameras.router, prefix="/cameras", tags=["cameras"])
app.include_router(execution.router, prefix="/execution", tags=["execution"])
app.include_router(analytics.router, prefix="/analytics", tags=["analytics"])
app.include_router(teleop.router, prefix="/teleop", tags=["teleop"])
app.include_router(recording.router, prefix="/recording", tags=["recording"])
app.include_router(training.router, prefix="/training", tags=["training"])
app.include_router(hardware.router, prefix="/hardware", tags=["hardware"])
app.include_router(homing.router, prefix="/homing", tags=["homing"])
app.include_router(calibration.router, prefix="/calibration", tags=["calibration"])
app.include_router(rl_training.router, prefix="/rl", tags=["rl-training"])
app.include_router(datasets.router, prefix="/datasets", tags=["datasets"])
app.include_router(policies.router, prefix="/policies", tags=["policies"])
app.include_router(system.router, prefix="/system", tags=["system"])
app.include_router(tools.router, tags=["tools"])

# Serve GLB mesh files for the 3D assembly viewer
MESHES_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/meshes", StaticFiles(directory=str(MESHES_DIR)), name="meshes")


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}


@app.get("/system/info")
async def system_info() -> dict:
    """System information for the frontend demo banner."""
    from nextis.state import get_state

    lerobot_available = False
    try:
        import lerobot  # noqa: F401

        lerobot_available = True
    except ImportError:
        pass

    mode = "mock"
    try:
        summary = get_state().arm_registry.get_status_summary()
        if summary["connected"] > 0:
            mode = "hardware"
    except Exception:
        pass

    return {
        "version": "0.1.0",
        "mode": mode,
        "assemblies": len(list(ASSEMBLIES_DIR.glob("*.json"))),
        "lerobotAvailable": lerobot_available,
    }
