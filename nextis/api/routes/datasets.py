"""Dataset routes — CRUD for recorded demonstration HDF5 files.

Provides listing, inspection, validation, and deletion of per-step
demonstration datasets stored under ``data/demos/``.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from nextis.api.schemas import DatasetDemoInfo, DatasetSummary
from nextis.config import DEMOS_DIR
from nextis.learning.dataset_service import DatasetService

logger = logging.getLogger(__name__)

router = APIRouter()

_service: DatasetService | None = None


def _get_service() -> DatasetService:
    """Lazy-init the DatasetService singleton."""
    global _service  # noqa: PLW0603
    if _service is None:
        _service = DatasetService(DEMOS_DIR)
    return _service


@router.get("/{assembly_id}/{step_id}")
async def list_datasets(assembly_id: str, step_id: str) -> DatasetSummary:
    """List all demos for a step with summary."""
    svc = _get_service()
    summary = svc.get_summary(assembly_id, step_id)
    return DatasetSummary(
        assembly_id=assembly_id,
        step_id=step_id,
        demo_count=summary["demo_count"],
        total_frames=summary["total_frames"],
        demos=[DatasetDemoInfo(**d) for d in summary["demos"]],
    )


@router.get("/{assembly_id}/{step_id}/{demo_id}")
async def get_dataset_info(assembly_id: str, step_id: str, demo_id: str) -> DatasetDemoInfo:
    """Get detailed info for a single demo."""
    svc = _get_service()
    info = svc.get_demo_info(assembly_id, step_id, demo_id)
    if info is None:
        raise HTTPException(status_code=404, detail=f"Demo '{demo_id}' not found")
    return DatasetDemoInfo(**info)


@router.post("/{assembly_id}/{step_id}/validate")
async def validate_datasets(assembly_id: str, step_id: str) -> dict:
    """Validate all demos for a step.

    Returns total, valid, invalid counts and per-demo results.
    """
    svc = _get_service()
    return svc.validate_all(assembly_id, step_id)


@router.delete("/{assembly_id}/{step_id}/{demo_id}")
async def delete_dataset(assembly_id: str, step_id: str, demo_id: str) -> dict:
    """Delete a single demo file."""
    svc = _get_service()
    deleted = svc.delete_demo(assembly_id, step_id, demo_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Demo '{demo_id}' not found")
    return {"deleted": demo_id}
