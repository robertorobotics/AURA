"""Policy routes — list, deploy, and delete trained policy checkpoints.

Policies are stored under ``data/policies/{assembly_id}/{step_id}/``.
BC checkpoints are ``policy.pt``, RL checkpoints are ``policy_rl.pt``.
"""

from __future__ import annotations

import logging
from pathlib import Path

import torch
from fastapi import APIRouter, HTTPException

from nextis.api.schemas import DeployRequest, PolicyInfoResponse
from nextis.assembly.models import AssemblyGraph
from nextis.config import ASSEMBLIES_DIR, POLICIES_DIR

logger = logging.getLogger(__name__)

router = APIRouter()

# Map policy_type to filename
_POLICY_FILES = {
    "bc": "policy.pt",
    "rl": "policy_rl.pt",
}


@router.get("/{assembly_id}/{step_id}")
async def list_policies(assembly_id: str, step_id: str) -> list[PolicyInfoResponse]:
    """List all trained policies (BC + RL) for a step."""
    policy_dir = POLICIES_DIR / assembly_id / step_id
    if not policy_dir.exists():
        return []

    policies: list[PolicyInfoResponse] = []
    for policy_type, filename in _POLICY_FILES.items():
        ckpt_path = policy_dir / filename
        if not ckpt_path.exists():
            continue

        # Read architecture from checkpoint config
        architecture = "act"
        try:
            ckpt = torch.load(str(ckpt_path), map_location="cpu", weights_only=True)
            architecture = ckpt.get("config", {}).get("architecture", "act")
        except Exception:
            pass

        policies.append(
            PolicyInfoResponse(
                policy_id=policy_type,
                policy_type=policy_type,
                checkpoint_path=str(ckpt_path),
                created_at=ckpt_path.stat().st_mtime,
                architecture=architecture,
            )
        )

    return policies


@router.post("/{assembly_id}/{step_id}/deploy")
async def deploy_policy(assembly_id: str, step_id: str, request: DeployRequest) -> dict:
    """Set a policy as active for a step.

    Updates the assembly JSON config: sets ``policy_id`` to the checkpoint
    path and ``handler`` to ``"policy"`` (for BC) or ``"rl_finetune"``
    (for RL).
    """
    policy_type = request.policy_type
    filename = _POLICY_FILES.get(policy_type)
    if filename is None:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid policy_type '{policy_type}'. Must be 'bc' or 'rl'.",
        )

    ckpt_path = POLICIES_DIR / assembly_id / step_id / filename
    if not ckpt_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"No {policy_type} checkpoint found for {assembly_id}/{step_id}",
        )

    # Find and update the assembly JSON
    assembly_path = _find_assembly_file(assembly_id)
    if assembly_path is None:
        raise HTTPException(status_code=404, detail=f"Assembly '{assembly_id}' not found")

    try:
        graph = AssemblyGraph.from_json_file(assembly_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load assembly: {e}") from e

    step = graph.steps.get(step_id)
    if step is None:
        raise HTTPException(status_code=404, detail=f"Step '{step_id}' not found in assembly")

    # Update step
    step.policy_id = str(ckpt_path)
    step.handler = "rl_finetune" if policy_type == "rl" else "policy"
    graph.to_json_file(assembly_path)

    logger.info(
        "Deployed %s policy for %s/%s: handler=%s",
        policy_type,
        assembly_id,
        step_id,
        step.handler,
    )
    return {
        "deployed": True,
        "policy_type": policy_type,
        "handler": step.handler,
        "checkpoint_path": str(ckpt_path),
    }


@router.delete("/{assembly_id}/{step_id}/{policy_id}")
async def delete_policy(assembly_id: str, step_id: str, policy_id: str) -> dict:
    """Delete a policy checkpoint file.

    Args:
        policy_id: ``"bc"`` or ``"rl"`` — maps to policy.pt or policy_rl.pt.
    """
    filename = _POLICY_FILES.get(policy_id)
    if filename is None:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid policy_id '{policy_id}'. Must be 'bc' or 'rl'.",
        )

    ckpt_path = POLICIES_DIR / assembly_id / step_id / filename
    if not ckpt_path.exists():
        raise HTTPException(status_code=404, detail=f"Policy '{policy_id}' not found")

    ckpt_path.unlink()
    logger.info("Deleted policy: %s", ckpt_path)
    return {"deleted": policy_id}


def _find_assembly_file(assembly_id: str) -> Path | None:
    """Find the assembly JSON file by ID."""
    for fpath in ASSEMBLIES_DIR.glob("*.json"):
        try:
            graph = AssemblyGraph.from_json_file(fpath)
            if graph.id == assembly_id:
                return fpath
        except Exception:
            continue
    return None
