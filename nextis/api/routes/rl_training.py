"""API routes for RL fine-tuning session management.

Manages per-step RL training sessions using StepRLTrainer. Only one
session can be active at a time (it holds the robot). Follows the same
background-task pattern as the BC training routes.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException

from nextis.api.schemas import RLStartRequest, RLTrainingState
from nextis.assembly.models import AssemblyGraph
from nextis.hardware.mock import MockLeader, MockRobot
from nextis.learning.policy_loader import PolicyLoader
from nextis.learning.rl_trainer import RLConfig, RLProgress, StepRLTrainer

logger = logging.getLogger(__name__)
router = APIRouter()

CONFIGS_DIR = Path(__file__).resolve().parents[3] / "configs" / "assemblies"

# Module-level session state
_rl_state = RLTrainingState()
_rl_task: asyncio.Task | None = None  # noqa: PLW0603
_trainer: StepRLTrainer | None = None  # noqa: PLW0603


@router.post("/step/{step_id}/start")
async def start_rl_training(step_id: str, request: RLStartRequest) -> dict[str, str]:
    """Start RL fine-tuning for an assembly step.

    Launches a background task running the RL training loop. Only one
    session can be active at a time.

    Args:
        step_id: Assembly step to fine-tune.
        request: RL training parameters.

    Returns:
        Status confirmation dict.
    """
    global _rl_state, _rl_task, _trainer  # noqa: PLW0603

    if _rl_state.status == "running":
        raise HTTPException(status_code=409, detail="RL session already running")

    # Load assembly
    path = CONFIGS_DIR / f"{request.assembly_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Assembly not found: {request.assembly_id}")

    graph = AssemblyGraph.from_json_file(path)
    step = graph.steps.get(step_id)
    if step is None:
        raise HTTPException(status_code=404, detail=f"Step not found: {step_id}")

    # Load BC policy if available
    loader = PolicyLoader()
    bc_policy = loader.load(request.assembly_id, step_id)

    # Reset state
    _rl_state = RLTrainingState(
        status="running",
        step_id=step_id,
        total_episodes=request.max_episodes,
    )

    config = RLConfig(
        max_episodes=request.max_episodes,
        movement_scale=request.movement_scale,
    )

    robot = MockRobot()
    leader = MockLeader()

    def on_progress(p: RLProgress) -> None:
        _rl_state.episode = p.episode
        _rl_state.success_rate = 1.0 if p.success else _rl_state.success_rate * 0.9
        _rl_state.intervention_rate = p.intervention_rate
        _rl_state.critic_loss = p.critic_loss
        _rl_state.actor_loss = p.actor_loss
        _rl_state.buffer_size = p.buffer_size

    _trainer = StepRLTrainer(
        robot=robot,
        leader=leader,
        step=step,
        assembly_id=request.assembly_id,
        bc_policy=bc_policy,
        config=config,
        on_progress=on_progress,
    )

    _rl_task = asyncio.create_task(_run_rl_session(_trainer, _rl_state))

    return {"status": "started", "stepId": step_id}


async def _run_rl_session(trainer: StepRLTrainer, state: RLTrainingState) -> None:
    """Background task that runs the RL training loop."""
    try:
        result = await trainer.train()
        state.status = "completed"
        state.success_rate = result.final_success_rate
        logger.info(
            "RL training completed: %d episodes, success_rate=%.2f",
            result.episodes_trained,
            result.final_success_rate,
        )
    except Exception as e:
        logger.error("RL training failed: %s", e, exc_info=True)
        state.status = "failed"


@router.post("/step/{step_id}/stop")
async def stop_rl_training(step_id: str) -> dict[str, str]:
    """Stop an active RL training session.

    Args:
        step_id: Step being trained (validated against active session).

    Returns:
        Status confirmation dict.
    """
    global _trainer  # noqa: PLW0603

    if _rl_state.status != "running":
        raise HTTPException(status_code=409, detail="No RL session running")

    if _rl_state.step_id != step_id:
        raise HTTPException(
            status_code=400,
            detail=f"Active session is for step {_rl_state.step_id}, not {step_id}",
        )

    if _trainer is not None:
        _trainer.request_stop()

    return {"status": "stopping", "stepId": step_id}


@router.get("/status")
async def get_rl_status() -> RLTrainingState:
    """Get the current RL training state."""
    return _rl_state


@router.get("/step/{step_id}/policy")
async def get_rl_policy_info(step_id: str, assembly_id: str = "") -> dict:
    """Check if an RL-finetuned checkpoint exists for a step.

    Args:
        step_id: Assembly step ID.
        assembly_id: Assembly identifier (query parameter).

    Returns:
        Dict with exists flag and checkpoint stats if available.
    """
    ckpt_path = Path("data/policies") / assembly_id / step_id / "policy_rl.pt"
    if not ckpt_path.exists():
        return {"exists": False, "stepId": step_id}

    return {"exists": True, "stepId": step_id, "checkpointPath": str(ckpt_path)}
