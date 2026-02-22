"""Execution lifecycle routes and WebSocket endpoint.

Manages a single Sequencer instance that walks the assembly graph.
State changes are pushed to connected WebSocket clients in real time.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field

from nextis.analytics.store import AnalyticsStore
from nextis.api.schemas import ExecutionState
from nextis.assembly.models import AssemblyGraph
from nextis.config import ANALYTICS_DIR
from nextis.config import ASSEMBLIES_DIR as CONFIGS_DIR
from nextis.control.primitives import PrimitiveLibrary
from nextis.execution.policy_router import PolicyRouter
from nextis.execution.sequencer import Sequencer, SequencerState

logger = logging.getLogger(__name__)

router = APIRouter()

# Module-level state — only one execution at a time.
_sequencer: Sequencer | None = None
_analytics_store: AnalyticsStore | None = None
_ws_connections: set[WebSocket] = set()


# ------------------------------------------------------------------
# WebSocket broadcast
# ------------------------------------------------------------------


def _broadcast_state(state: ExecutionState) -> None:
    """Push execution state to all connected WebSocket clients.

    Called synchronously from the Sequencer callback. Schedules async
    sends on the running event loop.
    """
    if not _ws_connections:
        return

    data = {"type": "execution_state", **state.model_dump(by_alias=True)}
    dead: list[WebSocket] = []

    loop = asyncio.get_event_loop()
    for ws in _ws_connections:
        try:
            loop.create_task(ws.send_json(data))
        except Exception:
            dead.append(ws)

    for ws in dead:
        _ws_connections.discard(ws)


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------


class StartRequest(BaseModel):
    """Request body for starting execution."""

    model_config = ConfigDict(populate_by_name=True)

    assembly_id: str = Field(alias="assemblyId")
    speed: float = Field(default=1.0, ge=0.1, le=20.0)
    demo_mode: bool = Field(default=False, alias="demoMode")


# ------------------------------------------------------------------
# REST endpoints
# ------------------------------------------------------------------


@router.get("/state")
async def get_execution_state() -> dict:
    """Return the current execution state."""
    if _sequencer is None:
        return ExecutionState().model_dump(by_alias=True)
    return _sequencer.get_execution_state().model_dump(by_alias=True)


@router.post("/start")
async def start_execution(request: StartRequest) -> dict[str, str]:
    """Start assembly execution.

    Loads the assembly graph from disk, creates a Sequencer, and starts
    it as an asyncio task. Returns immediately.
    """
    global _sequencer, _analytics_store  # noqa: PLW0603

    # Reject if already running
    if _sequencer is not None and _sequencer.state not in (
        SequencerState.IDLE,
        SequencerState.COMPLETE,
        SequencerState.ERROR,
    ):
        raise HTTPException(status_code=409, detail="Execution already in progress")

    # Load assembly graph
    path = CONFIGS_DIR / f"{request.assembly_id}.json"
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Assembly '{request.assembly_id}' not found",
        )

    graph = AssemblyGraph.from_json_file(path)
    logger.info("Loaded assembly '%s' with %d steps", graph.name, len(graph.step_order))

    # Build router — robot=None keeps primitives as stubs; assembly_id enables
    # policy loading.  PolicyRouter creates a MockRobot internally when it needs
    # observations for policy inference and no real robot is connected.
    speed_factor = 1.0 / request.speed
    primitives = PrimitiveLibrary(speed_factor=speed_factor)
    policy_router = PolicyRouter(
        primitive_library=primitives,
        robot=None,
        assembly_id=request.assembly_id,
    )
    _analytics_store = AnalyticsStore(root=ANALYTICS_DIR)

    _sequencer = Sequencer(
        graph=graph,
        on_state_change=_broadcast_state,
        router=policy_router,
        analytics=_analytics_store,
        demo_mode=request.demo_mode,
    )
    await _sequencer.start()
    return {"status": "ok"}


@router.post("/pause")
async def pause_execution() -> dict[str, str]:
    """Pause execution."""
    if _sequencer is None:
        raise HTTPException(status_code=409, detail="No active execution")
    await _sequencer.pause()
    return {"status": "ok"}


@router.post("/resume")
async def resume_execution() -> dict[str, str]:
    """Resume execution after a pause."""
    if _sequencer is None:
        raise HTTPException(status_code=409, detail="No active execution")
    await _sequencer.resume()
    return {"status": "ok"}


@router.post("/stop")
async def stop_execution() -> dict[str, str]:
    """Stop execution and reset to idle."""
    if _sequencer is None:
        raise HTTPException(status_code=409, detail="No active execution")
    await _sequencer.stop()
    return {"status": "ok"}


@router.post("/intervene")
async def intervene() -> dict[str, str]:
    """Signal that a human has completed the current step."""
    if _sequencer is None:
        raise HTTPException(status_code=409, detail="No active execution")
    await _sequencer.complete_human_step(success=True)
    return {"status": "ok"}


# ------------------------------------------------------------------
# WebSocket endpoint
# ------------------------------------------------------------------


@router.websocket("/ws")
async def execution_websocket(ws: WebSocket) -> None:
    """WebSocket for real-time execution state updates.

    Pushes ExecutionState JSON on every sequencer state change.
    Full path: /execution/ws (from router prefix + /ws).
    """
    await ws.accept()
    _ws_connections.add(ws)
    logger.info("Execution WS client connected (%d total)", len(_ws_connections))

    try:
        # Send current state on connect
        if _sequencer is not None:
            state = _sequencer.get_execution_state()
            await ws.send_json({"type": "execution_state", **state.model_dump(by_alias=True)})
        else:
            await ws.send_json(
                {"type": "execution_state", **ExecutionState().model_dump(by_alias=True)}
            )

        # Keep alive — read client messages (pings, etc.)
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _ws_connections.discard(ws)
        logger.info("Execution WS client disconnected (%d remaining)", len(_ws_connections))
