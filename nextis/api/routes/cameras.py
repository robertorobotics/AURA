"""Camera management and streaming routes.

All hardware-touching endpoints use ``def`` (not ``async def``) to run
in FastAPI's thread pool. MJPEG streaming uses StreamingResponse with
a generator that yields JPEG-encoded frames.
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import StreamingResponse

from nextis.api.schemas import CameraConfigRequest
from nextis.cameras.service import CameraConfig, CameraService, CameraType
from nextis.config import load_config, save_config

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_camera_service() -> CameraService:
    """Get CameraService from SystemState. Raises 503 if not ready."""
    from nextis.state import get_state

    state = get_state()
    if state.camera_service is None:
        raise HTTPException(503, "Camera service not initialized — no cameras configured")
    return state.camera_service


# ------------------------------------------------------------------
# Status
# ------------------------------------------------------------------


@router.get("/status")
def camera_status() -> dict:
    """Return status of all configured cameras."""
    from nextis.state import get_state

    state = get_state()
    if state.camera_service is None:
        return {}
    return state.camera_service.get_status()


# ------------------------------------------------------------------
# Connect / Disconnect
# ------------------------------------------------------------------


@router.post("/{camera_key}/connect")
def connect_camera(camera_key: str) -> dict:
    """Connect a configured camera by key."""
    service = _get_camera_service()
    if camera_key not in service.camera_keys:
        raise HTTPException(404, f"Camera '{camera_key}' not configured")
    ok = service.connect(camera_key)
    if not ok:
        status = service.get_status().get(camera_key, {})
        raise HTTPException(
            500,
            f"Failed to connect camera '{camera_key}': {status.get('error', 'unknown')}",
        )
    return {"status": "connected", "cameraKey": camera_key}


@router.post("/{camera_key}/disconnect")
def disconnect_camera(camera_key: str) -> dict:
    """Disconnect a camera by key."""
    service = _get_camera_service()
    service.disconnect(camera_key)
    return {"status": "disconnected", "cameraKey": camera_key}


@router.post("/{camera_key}/reconnect")
def reconnect_camera(camera_key: str) -> dict:
    """Disconnect then reconnect a camera."""
    service = _get_camera_service()
    service.disconnect(camera_key)
    ok = service.connect(camera_key)
    return {
        "status": "connected" if ok else "error",
        "cameraKey": camera_key,
    }


@router.post("/reconnect-all")
def reconnect_all() -> dict:
    """Disconnect and reconnect all cameras."""
    service = _get_camera_service()
    service.disconnect_all()
    results = service.connect_all()
    return {"results": results}


# ------------------------------------------------------------------
# Discovery
# ------------------------------------------------------------------


@router.get("/scan")
def scan_cameras() -> list[dict]:
    """Scan for available camera devices on the system."""
    from nextis.cameras.discovery import discover_cameras

    results = discover_cameras()
    return [
        {
            "devicePath": r.device_path,
            "name": r.name,
            "cameraType": r.camera_type,
            "isRealsense": r.is_realsense,
        }
        for r in results
    ]


# ------------------------------------------------------------------
# Snapshot
# ------------------------------------------------------------------


@router.get("/{camera_key}/snapshot")
def camera_snapshot(camera_key: str) -> Response:
    """Return a single JPEG frame from the camera."""
    import cv2

    service = _get_camera_service()
    frame = service.get_frame(camera_key)
    if frame is None:
        raise HTTPException(404, f"No frame available for '{camera_key}'")

    _, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return Response(content=jpeg.tobytes(), media_type="image/jpeg")


# ------------------------------------------------------------------
# MJPEG Stream
# ------------------------------------------------------------------


@router.get("/{camera_key}/stream")
def camera_stream(
    camera_key: str,
    fps: int = Query(15, ge=1, le=30, description="Target stream FPS"),
    quality: int = Query(70, ge=10, le=100, description="JPEG quality"),
) -> StreamingResponse:
    """MJPEG live video stream.

    Uses ``multipart/x-mixed-replace`` for browser-native MJPEG rendering
    (works in ``<img>`` tags without JavaScript).
    """
    service = _get_camera_service()
    if camera_key not in service.camera_keys:
        raise HTTPException(404, f"Camera '{camera_key}' not configured")

    return StreamingResponse(
        _mjpeg_generator(service, camera_key, fps, quality),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


def _mjpeg_generator(
    service: CameraService,
    camera_key: str,
    fps: int,
    quality: int,
):
    """Yield JPEG frames as multipart boundary chunks."""
    import cv2

    dt = 1.0 / fps
    encode_params = [cv2.IMWRITE_JPEG_QUALITY, quality]

    while True:
        start = time.monotonic()
        frame = service.get_frame(camera_key)
        if frame is not None:
            _, jpeg = cv2.imencode(".jpg", frame, encode_params)
            yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg.tobytes() + b"\r\n")
        else:
            # Yield a small placeholder so the stream stays alive
            time.sleep(0.5)
            continue

        elapsed = time.monotonic() - start
        if elapsed < dt:
            time.sleep(dt - elapsed)


# ------------------------------------------------------------------
# Config CRUD
# ------------------------------------------------------------------


@router.get("/config")
def get_camera_config() -> dict:
    """Return the current camera configuration from settings.yaml."""
    config = load_config()
    return config.get("cameras", {})


@router.post("/config")
def update_camera_config(request: CameraConfigRequest) -> dict:
    """Add or update a camera in config and persist to settings.yaml.

    If the camera is currently connected, it will be reconnected with
    the new settings.
    """
    from nextis.state import get_state

    state = get_state()
    full_config = load_config()
    cameras = full_config.setdefault("cameras", {})

    cameras[request.key] = {
        "type": request.camera_type,
        "index_or_path": request.index_or_path,
        "width": request.width,
        "height": request.height,
        "fps": request.fps,
        "serial_number_or_name": request.serial_number_or_name,
        "use_depth": request.use_depth,
    }
    save_config(full_config)

    # Update service if running
    if state.camera_service is not None:
        cfg = CameraConfig(
            key=request.key,
            camera_type=CameraType(request.camera_type),
            index_or_path=request.index_or_path,
            width=request.width,
            height=request.height,
            fps=request.fps,
            serial_number_or_name=request.serial_number_or_name,
            use_depth=request.use_depth,
        )
        if request.key in state.camera_service.camera_keys:
            state.camera_service.disconnect(request.key)
            state.camera_service.remove_camera(request.key)
        state.camera_service.add_camera(cfg)

    return {"status": "saved", "cameraKey": request.key}


@router.delete("/{camera_key}/config")
def remove_camera_config(camera_key: str) -> dict:
    """Remove a camera from config. Disconnects if connected."""
    from nextis.state import get_state

    state = get_state()
    full_config = load_config()
    cameras = full_config.get("cameras", {})

    if camera_key not in cameras:
        raise HTTPException(404, f"Camera '{camera_key}' not in config")

    del cameras[camera_key]
    save_config(full_config)

    if state.camera_service is not None:
        state.camera_service.remove_camera(camera_key)

    return {"status": "removed", "cameraKey": camera_key}
