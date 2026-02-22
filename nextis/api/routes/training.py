"""Training routes — per-step policy training with real pipeline.

Supports ACT, Diffusion, and PI0.5 (flow matching) architectures.
Jobs are persisted to disk and survive server restarts. Cancellation
is supported via inter-epoch flag checking.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException

from nextis.api.schemas import TrainingJobState, TrainingPresetResponse, TrainRequest
from nextis.config import DEMOS_DIR, POLICIES_DIR, TRAINING_JOBS_DIR
from nextis.errors import TrainingError
from nextis.learning.training_service import PRESETS, TrainingJob, TrainingService

logger = logging.getLogger(__name__)

router = APIRouter()

_service: TrainingService | None = None


def _get_service() -> TrainingService:
    """Lazy-init the TrainingService singleton."""
    global _service  # noqa: PLW0603
    if _service is None:
        _service = TrainingService(TRAINING_JOBS_DIR, DEMOS_DIR, POLICIES_DIR)
        _service.load_jobs_from_disk()
    return _service


def _job_to_schema(job: TrainingJob) -> TrainingJobState:
    """Convert a TrainingJob to the API schema."""
    return TrainingJobState(
        job_id=job.job_id,
        step_id=job.step_id,
        status=job.status,
        progress=job.progress,
        loss=job.loss,
        val_loss=job.val_loss,
        error=job.error,
        checkpoint_path=job.checkpoint_path,
    )


@router.post("/step/{step_id}/train")
async def start_training(step_id: str, request: TrainRequest) -> TrainingJobState:
    """Launch a training job for a specific assembly step.

    Builds a dataset from recorded HDF5 demos, trains a policy using
    the specified architecture, and saves the checkpoint. Training
    runs as a background task.

    Args:
        step_id: Assembly step to train a policy for.
        request: Training configuration (architecture, num_steps, assembly_id).
    """
    service = _get_service()

    try:
        job = service.start_training(
            step_id=step_id,
            assembly_id=request.assembly_id,
            architecture=request.architecture,
            num_steps=request.num_steps,
        )
    except TrainingError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    logger.info(
        "Training job created: job=%s step=%s arch=%s assembly=%s",
        job.job_id,
        step_id,
        request.architecture,
        request.assembly_id,
    )

    # Launch training in background
    asyncio.create_task(service.run_training(job))

    return _job_to_schema(job)


@router.get("/jobs/{job_id}")
async def get_training_job(job_id: str) -> TrainingJobState:
    """Get the status of a training job."""
    service = _get_service()
    job = service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Training job '{job_id}' not found")
    return _job_to_schema(job)


@router.get("/jobs", response_model=list[TrainingJobState])
async def list_training_jobs() -> list[TrainingJobState]:
    """List all training jobs."""
    service = _get_service()
    return [_job_to_schema(j) for j in service.list_jobs()]


@router.post("/jobs/{job_id}/cancel")
async def cancel_training_job(job_id: str) -> dict:
    """Cancel a running training job.

    The job will be cancelled at the next epoch boundary.
    """
    service = _get_service()
    cancelled = service.cancel_job(job_id)
    if not cancelled:
        job = service.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"Training job '{job_id}' not found")
        raise HTTPException(
            status_code=400,
            detail=f"Job '{job_id}' is not running (status: {job.status})",
        )
    return {"cancelled": True, "job_id": job_id}


@router.get("/presets", response_model=list[TrainingPresetResponse])
async def get_training_presets() -> list[TrainingPresetResponse]:
    """List available training presets."""
    return [TrainingPresetResponse(**preset) for preset in PRESETS.values()]
