"""Tool, trigger, and tool-pairing management routes.

Handles CRUD for end-effector tools (screwdrivers, grippers), trigger
devices (foot pedals, buttons), and trigger-to-tool pairings.

All hardware-touching endpoints use ``def`` (not ``async def``) so FastAPI
runs them in the thread pool.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from nextis.api.schemas import (
    AddToolRequest,
    AddTriggerRequest,
    CreateToolPairingRequest,
    RemoveToolPairingRequest,
    UpdateToolRequest,
    UpdateTriggerRequest,
)
from nextis.tools.registry import ToolRegistryService

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_tool_registry() -> ToolRegistryService:
    """Return the shared ToolRegistryService from SystemState."""
    from nextis.state import get_state

    reg = get_state().tool_registry
    if reg is None:
        raise HTTPException(503, "Tool registry not initialized")
    return reg


# ------------------------------------------------------------------
# Tool routes
# ------------------------------------------------------------------


@router.get("/tools")
async def list_tools() -> list[dict]:
    """List all tools with current status."""
    return _get_tool_registry().get_all_tools()


@router.post("/tools")
async def add_tool(request: AddToolRequest) -> dict:
    """Add a new tool to the registry."""
    result = _get_tool_registry().add_tool(request.model_dump(by_alias=False))
    if not result["success"]:
        raise HTTPException(400, result.get("error", "Failed to add tool"))
    return result


@router.get("/tools/{tool_id}")
async def get_tool(tool_id: str) -> dict:
    """Get a single tool by ID."""
    tool = _get_tool_registry().get_tool(tool_id)
    if tool is None:
        raise HTTPException(404, f"Tool '{tool_id}' not found")
    return tool


@router.put("/tools/{tool_id}")
async def update_tool(tool_id: str, request: UpdateToolRequest) -> dict:
    """Update tool properties."""
    updates = {k: v for k, v in request.model_dump(by_alias=False).items() if v is not None}
    if not updates:
        raise HTTPException(400, "No fields to update")
    result = _get_tool_registry().update_tool(tool_id, **updates)
    if not result["success"]:
        raise HTTPException(400, result.get("error", "Update failed"))
    return result


@router.delete("/tools/{tool_id}")
async def remove_tool(tool_id: str) -> dict:
    """Remove a tool (disconnects first if connected)."""
    result = _get_tool_registry().remove_tool(tool_id)
    if not result["success"]:
        raise HTTPException(404, result.get("error", "Tool not found"))
    return result


@router.post("/tools/{tool_id}/connect")
def connect_tool(tool_id: str) -> dict:
    """Connect a tool's motor bus."""
    result = _get_tool_registry().connect_tool(tool_id)
    if not result["success"]:
        raise HTTPException(400, result.get("error", "Connection failed"))
    return result


@router.post("/tools/{tool_id}/disconnect")
def disconnect_tool(tool_id: str) -> dict:
    """Disconnect a tool."""
    result = _get_tool_registry().disconnect_tool(tool_id)
    if not result["success"]:
        raise HTTPException(400, result.get("error", "Disconnect failed"))
    return result


@router.post("/tools/{tool_id}/activate")
def activate_tool(tool_id: str) -> dict:
    """Start a tool (e.g. spin screwdriver)."""
    result = _get_tool_registry().activate_tool(tool_id)
    if not result["success"]:
        raise HTTPException(400, result.get("error", "Activation failed"))
    return result


@router.post("/tools/{tool_id}/deactivate")
def deactivate_tool(tool_id: str) -> dict:
    """Stop a tool."""
    result = _get_tool_registry().deactivate_tool(tool_id)
    if not result["success"]:
        raise HTTPException(400, result.get("error", "Deactivation failed"))
    return result


# ------------------------------------------------------------------
# Trigger routes
# ------------------------------------------------------------------


@router.get("/triggers")
async def list_triggers() -> list[dict]:
    """List all triggers with current status."""
    return _get_tool_registry().get_all_triggers()


@router.post("/triggers")
async def add_trigger(request: AddTriggerRequest) -> dict:
    """Add a new trigger device."""
    result = _get_tool_registry().add_trigger(request.model_dump(by_alias=False))
    if not result["success"]:
        raise HTTPException(400, result.get("error", "Failed to add trigger"))
    return result


@router.get("/triggers/{trigger_id}")
async def get_trigger(trigger_id: str) -> dict:
    """Get a single trigger by ID."""
    trigger = _get_tool_registry().get_trigger(trigger_id)
    if trigger is None:
        raise HTTPException(404, f"Trigger '{trigger_id}' not found")
    return trigger


@router.put("/triggers/{trigger_id}")
async def update_trigger(trigger_id: str, request: UpdateTriggerRequest) -> dict:
    """Update trigger properties."""
    updates = {k: v for k, v in request.model_dump(by_alias=False).items() if v is not None}
    if not updates:
        raise HTTPException(400, "No fields to update")
    result = _get_tool_registry().update_trigger(trigger_id, **updates)
    if not result["success"]:
        raise HTTPException(400, result.get("error", "Update failed"))
    return result


@router.delete("/triggers/{trigger_id}")
async def remove_trigger(trigger_id: str) -> dict:
    """Remove a trigger (disconnects first if connected)."""
    result = _get_tool_registry().remove_trigger(trigger_id)
    if not result["success"]:
        raise HTTPException(404, result.get("error", "Trigger not found"))
    return result


@router.post("/triggers/{trigger_id}/connect")
def connect_trigger(trigger_id: str) -> dict:
    """Connect a trigger device."""
    result = _get_tool_registry().connect_trigger(trigger_id)
    if not result["success"]:
        raise HTTPException(400, result.get("error", "Connection failed"))
    return result


@router.post("/triggers/{trigger_id}/disconnect")
def disconnect_trigger(trigger_id: str) -> dict:
    """Disconnect a trigger device."""
    result = _get_tool_registry().disconnect_trigger(trigger_id)
    if not result["success"]:
        raise HTTPException(400, result.get("error", "Disconnect failed"))
    return result


# ------------------------------------------------------------------
# Tool-trigger pairing routes
# ------------------------------------------------------------------


@router.get("/tool-pairings")
async def list_tool_pairings() -> list[dict]:
    """List all trigger-to-tool pairings."""
    return _get_tool_registry().get_pairings()


@router.post("/tool-pairings")
async def create_tool_pairing(request: CreateToolPairingRequest) -> dict:
    """Create a trigger-to-tool pairing."""
    result = _get_tool_registry().create_pairing(
        request.trigger_id, request.tool_id, request.name, request.action
    )
    if not result["success"]:
        raise HTTPException(400, result.get("error", "Failed to create pairing"))
    return result


@router.delete("/tool-pairings")
async def remove_tool_pairing(request: RemoveToolPairingRequest) -> dict:
    """Remove a trigger-to-tool pairing."""
    result = _get_tool_registry().remove_pairing(request.trigger_id, request.tool_id)
    if not result["success"]:
        raise HTTPException(404, result.get("error", "Pairing not found"))
    return result
