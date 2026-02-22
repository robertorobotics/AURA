"""Step-segmented recording routes.

Manages a DemoRecorder stored on SystemState that captures teleop data
for a specific assembly step.  The recorder runs alongside the teleop
loop, sampling at 50 Hz.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from nextis.api.schemas import DemoInfo, RecordingStartRequest
from nextis.errors import RecordingError
from nextis.learning.recorder import DEFAULT_DATA_DIR, DemoRecorder

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/step/{step_id}/start")
async def start_recording(step_id: str, request: RecordingStartRequest) -> dict:
    """Start recording a demonstration for a specific assembly step.

    Requires an active teleop session.

    Args:
        step_id: Assembly step being demonstrated.
        request: Body with assemblyId.
    """
    from nextis.state import get_state

    state = get_state()

    if state.recorder is not None and state.recorder.is_recording:
        raise HTTPException(status_code=409, detail="Recording already in progress")

    loop = state.teleop_loop
    if loop is None or not loop.is_running:
        raise HTTPException(
            status_code=409,
            detail="No active teleop session. Start teleop before recording.",
        )

    try:
        # Gather connected camera keys for image recording
        camera_fn = None
        camera_keys: list[str] = []
        if state.camera_service is not None:
            camera_keys = state.camera_service.connected_keys
            if camera_keys:
                camera_fn = state.camera_service.get_frame

        recorder = DemoRecorder(
            assembly_id=request.assembly_id,
            step_id=step_id,
            camera_keys=camera_keys,
        )
        recorder.start(
            robot_state_fn=lambda: loop.robot.get_observation(),
            action_fn=lambda: loop.latest_action,
            torque_fn=lambda: loop.robot.get_torques(),
            camera_fn=camera_fn,
        )
        state.recorder = recorder
    except RecordingError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return {
        "status": "recording",
        "demoId": recorder.demo_id,
        "stepId": step_id,
        "assemblyId": request.assembly_id,
    }


@router.post("/stop")
async def stop_recording() -> DemoInfo:
    """Stop the current recording and flush to HDF5."""
    from nextis.state import get_state

    state = get_state()

    if state.recorder is None or not state.recorder.is_recording:
        raise HTTPException(status_code=409, detail="No active recording")

    try:
        metadata = state.recorder.stop()
    except RecordingError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    info = DemoInfo(
        demo_id=metadata.demo_id,
        assembly_id=metadata.assembly_id,
        step_id=metadata.step_id,
        num_frames=metadata.num_frames,
        duration_s=metadata.duration_s,
        file_path=str(metadata.file_path),
        timestamp=metadata.timestamp,
    )
    state.recorder = None
    return info


@router.post("/discard")
async def discard_recording() -> dict[str, str]:
    """Discard the current recording."""
    from nextis.state import get_state

    state = get_state()

    if state.recorder is None:
        raise HTTPException(status_code=409, detail="No recording to discard")

    state.recorder.discard()
    state.recorder = None
    return {"status": "discarded"}


@router.get("/demos/{assembly_id}/{step_id}", response_model=list[DemoInfo])
async def list_demos(assembly_id: str, step_id: str) -> list[DemoInfo]:
    """List all recorded demos for a given assembly step."""
    demo_dir = DEFAULT_DATA_DIR / assembly_id / step_id
    if not demo_dir.exists():
        return []

    demos: list[DemoInfo] = []
    for hdf5_path in sorted(demo_dir.glob("*.hdf5")):
        try:
            import h5py

            with h5py.File(str(hdf5_path), "r") as f:
                nf = int(f.attrs.get("num_frames", 0))
                hz = float(f.attrs.get("recording_hz", 50))
                demos.append(
                    DemoInfo(
                        demo_id=str(f.attrs.get("demo_id", hdf5_path.stem)),
                        assembly_id=str(f.attrs.get("assembly_id", assembly_id)),
                        step_id=str(f.attrs.get("step_id", step_id)),
                        num_frames=nf,
                        duration_s=round(nf / hz, 2) if hz > 0 else 0.0,
                        file_path=str(hdf5_path),
                        timestamp=float(f.attrs.get("timestamp", 0.0)),
                    )
                )
        except Exception as e:
            logger.warning("Failed to read demo %s: %s", hdf5_path, e)

    return demos


@router.post("/demos/{assembly_id}/{step_id}/{demo_id}/delete")
async def delete_demo(assembly_id: str, step_id: str, demo_id: str) -> dict:
    """Delete a specific recorded demo."""
    demo_dir = DEFAULT_DATA_DIR / assembly_id / step_id
    matching = list(demo_dir.glob(f"{demo_id}*.hdf5"))
    if not matching:
        raise HTTPException(404, f"Demo '{demo_id}' not found")
    for f in matching:
        f.unlink()
    return {"status": "deleted", "demoId": demo_id}
