"""System lifecycle and config API routes.

Provides system status, config inspection, and restart control.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/status")
async def system_status() -> dict:
    """Return current system state: phase, arm count, active sessions."""
    from nextis.state import get_state

    return get_state().get_status_dict()


@router.get("/config")
async def get_config() -> dict:
    """Return the full loaded configuration (read-only view)."""
    from nextis.state import get_state

    return get_state().config_data


@router.post("/restart")
async def restart_system(background_tasks: BackgroundTasks) -> dict[str, str]:
    """Reload configuration and re-initialize all services.

    Runs in a background task so the response returns immediately.
    """
    background_tasks.add_task(_do_reload)
    return {"status": "restarting"}


def _do_reload() -> None:
    """Background task for system reload."""
    from nextis.state import get_state

    try:
        get_state().reload()
        logger.info("System reload complete")
    except Exception as exc:
        logger.error("System reload failed: %s", exc)
