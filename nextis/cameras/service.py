"""CameraService — threaded camera capture with ZOH frame access.

Each connected camera runs a dedicated capture thread. Readers call
``get_frame(camera_key)`` to get the latest frame (zero-order hold).
A health monitor thread runs every 5 seconds to detect stale cameras.
"""

from __future__ import annotations

import contextlib
import logging
import threading
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import numpy as np

from nextis.errors import CameraError

logger = logging.getLogger(__name__)

# Graceful optional imports
try:
    import pyrealsense2 as rs

    HAS_REALSENSE = True
except ImportError:
    rs = None  # type: ignore[assignment]
    HAS_REALSENSE = False

HEALTH_CHECK_INTERVAL_S = 5.0
STALE_FRAME_THRESHOLD_S = 10.0
MAX_RECONNECT_ATTEMPTS = 3
RECONNECT_BACKOFF_BASE_S = 2.0


class CameraType(StrEnum):
    """Supported camera backends."""

    OPENCV = "opencv"
    INTELREALSENSE = "intelrealsense"


class CameraStatus(StrEnum):
    """Connection status of a managed camera."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


@dataclass
class CameraConfig:
    """Configuration for a single camera.

    Matches the YAML schema under ``cameras:`` in settings.yaml.
    """

    key: str
    camera_type: CameraType = CameraType.OPENCV
    index_or_path: str | int = 0
    width: int = 640
    height: int = 480
    fps: int = 30
    serial_number_or_name: str = ""
    use_depth: bool = False


@dataclass
class _CameraState:
    """Internal per-camera runtime state."""

    config: CameraConfig
    status: CameraStatus = CameraStatus.DISCONNECTED
    capture: Any = None
    pipeline: Any = None  # RealSense pipeline
    thread: threading.Thread | None = None
    running: bool = False
    frame: np.ndarray | None = None
    depth_frame: np.ndarray | None = None
    frame_lock: threading.Lock = field(default_factory=threading.Lock)
    last_frame_time: float = 0.0
    error: str | None = None
    reconnect_count: int = 0


class CameraService:
    """Manages camera connections, capture threads, and frame access.

    Thread model:
      - One daemon capture thread per connected camera.
      - One daemon health monitor thread (5s interval).
      - Frame access via ``get_frame()`` is lock-protected and non-blocking.

    Args:
        camera_configs: List of camera configurations from parsed YAML.
    """

    def __init__(self, camera_configs: list[CameraConfig] | None = None) -> None:
        self._cameras: dict[str, _CameraState] = {}
        self._lock = threading.Lock()
        self._connect_lock = threading.Lock()
        self._health_thread: threading.Thread | None = None
        self._running = False

        if camera_configs:
            for cfg in camera_configs:
                self._cameras[cfg.key] = _CameraState(config=cfg)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the health monitor. Does NOT auto-connect cameras."""
        self._running = True
        self._health_thread = threading.Thread(
            target=self._health_loop,
            daemon=True,
            name="CameraHealthMonitor",
        )
        self._health_thread.start()
        logger.info(
            "CameraService started: %d cameras configured",
            len(self._cameras),
        )

    def shutdown(self) -> None:
        """Disconnect all cameras and stop the health monitor."""
        self._running = False

        # Disconnect all cameras
        for key in list(self._cameras):
            try:
                self.disconnect(key)
            except Exception as exc:
                logger.error("Error disconnecting camera %s: %s", key, exc)

        # Join health thread
        if self._health_thread and self._health_thread.is_alive():
            self._health_thread.join(timeout=3.0)
        self._health_thread = None

        logger.info("CameraService shut down")

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def connect(self, camera_key: str) -> bool:
        """Connect a specific camera by key.

        Opens the appropriate backend (OpenCV or RealSense), starts the
        capture thread, and sets status to CONNECTED.

        Args:
            camera_key: Camera identifier from config.

        Returns:
            ``True`` if connection succeeded, ``False`` otherwise.
        """
        with self._lock:
            state = self._cameras.get(camera_key)
            if state is None:
                raise CameraError(f"Camera '{camera_key}' not configured")
            if state.status == CameraStatus.CONNECTED:
                return True
            state.status = CameraStatus.CONNECTING
            state.error = None

        with self._connect_lock:
            try:
                ok = self._open_camera(state)
                if not ok:
                    state.status = CameraStatus.ERROR
                    state.error = "Failed to open camera device"
                    return False

                # Start capture thread
                state.running = True
                state.thread = threading.Thread(
                    target=self._capture_loop,
                    args=(camera_key,),
                    daemon=True,
                    name=f"CameraCapture-{camera_key}",
                )
                state.thread.start()
                state.status = CameraStatus.CONNECTED
                state.reconnect_count = 0
                logger.info("Camera '%s' connected", camera_key)
                return True

            except Exception as exc:
                state.status = CameraStatus.ERROR
                state.error = str(exc)
                logger.error("Failed to connect camera '%s': %s", camera_key, exc)
                return False

    def disconnect(self, camera_key: str) -> None:
        """Disconnect a specific camera. Stops its capture thread.

        Args:
            camera_key: Camera identifier from config.
        """
        state = self._cameras.get(camera_key)
        if state is None:
            return

        # Stop capture thread
        state.running = False
        if state.thread and state.thread.is_alive():
            state.thread.join(timeout=2.0)
        state.thread = None

        # Release hardware
        self._release_camera(state)

        state.status = CameraStatus.DISCONNECTED
        state.frame = None
        state.depth_frame = None
        state.error = None

    def connect_all(self) -> dict[str, bool]:
        """Connect all configured cameras.

        Returns:
            Dict of camera_key -> success boolean.
        """
        results: dict[str, bool] = {}
        for key in self._cameras:
            results[key] = self.connect(key)
        return results

    def disconnect_all(self) -> None:
        """Disconnect all cameras."""
        for key in list(self._cameras):
            self.disconnect(key)

    # ------------------------------------------------------------------
    # Frame access (ZOH — non-blocking)
    # ------------------------------------------------------------------

    def get_frame(self, camera_key: str) -> np.ndarray | None:
        """Get the latest frame for a camera (ZOH). Non-blocking.

        Args:
            camera_key: Camera identifier.

        Returns:
            BGR uint8 numpy array ``(H, W, 3)``, or ``None`` if no frame.
        """
        state = self._cameras.get(camera_key)
        if state is None:
            return None
        with state.frame_lock:
            if state.frame is not None:
                return state.frame.copy()
        return None

    def get_depth_frame(self, camera_key: str) -> np.ndarray | None:
        """Get the latest depth frame (RealSense only). Non-blocking.

        Returns:
            uint16 numpy array ``(H, W)``, or ``None`` if not available.
        """
        state = self._cameras.get(camera_key)
        if state is None:
            return None
        with state.frame_lock:
            if state.depth_frame is not None:
                return state.depth_frame.copy()
        return None

    def get_all_frames(self) -> dict[str, np.ndarray]:
        """Get the latest frame from each connected camera.

        Returns:
            Dict of camera_key -> BGR frame. Only includes cameras with
            a frame available.
        """
        frames: dict[str, np.ndarray] = {}
        for key, state in self._cameras.items():
            if state.status == CameraStatus.CONNECTED:
                with state.frame_lock:
                    if state.frame is not None:
                        frames[key] = state.frame.copy()
        return frames

    # ------------------------------------------------------------------
    # Status & config
    # ------------------------------------------------------------------

    def get_status(self) -> dict[str, dict]:
        """Get status of all cameras for the API.

        Returns:
            Dict of camera_key -> status info dict.
        """
        result: dict[str, dict] = {}
        now = time.monotonic()
        for key, state in self._cameras.items():
            frame_age = now - state.last_frame_time if state.last_frame_time > 0 else -1
            result[key] = {
                "status": state.status.value,
                "cameraType": state.config.camera_type.value,
                "width": state.config.width,
                "height": state.config.height,
                "fps": state.config.fps,
                "lastFrameAgeS": round(frame_age, 2) if frame_age >= 0 else None,
                "error": state.error,
                "reconnectCount": state.reconnect_count,
            }
        return result

    def add_camera(self, config: CameraConfig) -> None:
        """Add a new camera configuration at runtime.

        Args:
            config: Camera configuration.
        """
        with self._lock:
            if config.key in self._cameras:
                raise CameraError(f"Camera '{config.key}' already exists")
            self._cameras[config.key] = _CameraState(config=config)

    def remove_camera(self, camera_key: str) -> None:
        """Remove a camera (disconnect first if connected).

        Args:
            camera_key: Camera identifier to remove.
        """
        self.disconnect(camera_key)
        with self._lock:
            self._cameras.pop(camera_key, None)

    @property
    def connected_keys(self) -> list[str]:
        """List of camera keys currently connected."""
        return [k for k, s in self._cameras.items() if s.status == CameraStatus.CONNECTED]

    @property
    def camera_keys(self) -> list[str]:
        """List of all configured camera keys."""
        return list(self._cameras)

    # ------------------------------------------------------------------
    # Internal — camera backends
    # ------------------------------------------------------------------

    def _open_camera(self, state: _CameraState) -> bool:
        """Open the appropriate camera backend.

        Returns:
            ``True`` on success.
        """
        if state.config.camera_type == CameraType.OPENCV:
            return self._open_opencv(state)
        elif state.config.camera_type == CameraType.INTELREALSENSE:
            return self._open_realsense(state)
        else:
            state.error = f"Unknown camera type: {state.config.camera_type}"
            return False

    def _open_opencv(self, state: _CameraState) -> bool:
        """Open an OpenCV VideoCapture with fallback strategies.

        Tries: device path string → integer index → CAP_V4L2 backend.
        """
        import cv2

        cfg = state.config
        device = cfg.index_or_path

        # Tier 1: Try device as-is (string path or int)
        cap = cv2.VideoCapture(device)
        if not cap.isOpened() and isinstance(device, str):
            # Tier 2: Try parsing as integer index
            try:
                cap.release()
                cap = cv2.VideoCapture(int(device))
            except (ValueError, TypeError):
                pass

        if not cap.isOpened():
            # Tier 3: Try with V4L2 backend explicitly
            cap.release()
            cap = cv2.VideoCapture(device, cv2.CAP_V4L2)

        if not cap.isOpened():
            cap.release()
            state.error = f"Cannot open camera at {device}"
            return False

        # Configure resolution and FPS
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, cfg.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cfg.height)
        cap.set(cv2.CAP_PROP_FPS, cfg.fps)

        # Verify with a test read
        ret, frame = cap.read()
        if not ret or frame is None:
            cap.release()
            state.error = f"Camera at {device} opened but cannot read frames"
            return False

        state.capture = cap
        logger.info(
            "OpenCV camera '%s' opened at %s (%.0fx%.0f @ %.0ffps)",
            state.config.key,
            device,
            cap.get(cv2.CAP_PROP_FRAME_WIDTH),
            cap.get(cv2.CAP_PROP_FRAME_HEIGHT),
            cap.get(cv2.CAP_PROP_FPS),
        )
        return True

    def _open_realsense(self, state: _CameraState) -> bool:
        """Open a RealSense pipeline with color (+ optional depth) stream."""
        if not HAS_REALSENSE:
            state.error = "pyrealsense2 not installed"
            return False

        cfg = state.config
        pipeline = rs.pipeline()
        rs_config = rs.config()

        # Filter by serial number if specified
        if cfg.serial_number_or_name:
            rs_config.enable_device(cfg.serial_number_or_name)

        rs_config.enable_stream(
            rs.stream.color,
            cfg.width,
            cfg.height,
            rs.format.bgr8,
            cfg.fps,
        )
        if cfg.use_depth:
            rs_config.enable_stream(
                rs.stream.depth,
                cfg.width,
                cfg.height,
                rs.format.z16,
                cfg.fps,
            )

        try:
            pipeline.start(rs_config)
        except Exception as exc:
            state.error = f"RealSense pipeline start failed: {exc}"
            return False

        state.pipeline = pipeline
        logger.info(
            "RealSense camera '%s' opened (%dx%d @ %dfps, depth=%s)",
            cfg.key,
            cfg.width,
            cfg.height,
            cfg.fps,
            cfg.use_depth,
        )
        return True

    def _release_camera(self, state: _CameraState) -> None:
        """Release camera hardware resources."""
        if state.capture is not None:
            with contextlib.suppress(Exception):
                state.capture.release()
            state.capture = None

        if state.pipeline is not None:
            with contextlib.suppress(Exception):
                state.pipeline.stop()
            state.pipeline = None

    # ------------------------------------------------------------------
    # Internal — capture loop
    # ------------------------------------------------------------------

    def _capture_loop(self, camera_key: str) -> None:
        """Per-camera capture loop. Runs in a daemon thread."""
        state = self._cameras[camera_key]
        cfg = state.config
        dt = 1.0 / cfg.fps
        error_count = 0

        while state.running:
            loop_start = time.perf_counter()
            try:
                if cfg.camera_type == CameraType.OPENCV:
                    self._read_opencv(state)
                elif cfg.camera_type == CameraType.INTELREALSENSE:
                    self._read_realsense(state)
                error_count = 0
            except Exception as exc:
                error_count += 1
                if error_count % (cfg.fps * 5) == 1:  # Log every ~5s
                    logger.warning(
                        "Camera '%s' read error (%d): %s",
                        camera_key,
                        error_count,
                        exc,
                    )

            elapsed = time.perf_counter() - loop_start
            sleep_time = dt - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    def _read_opencv(self, state: _CameraState) -> None:
        """Read a frame from an OpenCV camera."""
        ret, frame = state.capture.read()
        if ret and frame is not None:
            with state.frame_lock:
                state.frame = frame
                state.last_frame_time = time.monotonic()

    def _read_realsense(self, state: _CameraState) -> None:
        """Read a frameset from a RealSense pipeline."""
        frames = state.pipeline.wait_for_frames(timeout_ms=1000)
        color = frames.get_color_frame()
        if color:
            with state.frame_lock:
                state.frame = np.asanyarray(color.get_data())
                state.last_frame_time = time.monotonic()

        if state.config.use_depth:
            depth = frames.get_depth_frame()
            if depth:
                with state.frame_lock:
                    state.depth_frame = np.asanyarray(depth.get_data())

    # ------------------------------------------------------------------
    # Internal — health monitor
    # ------------------------------------------------------------------

    def _health_loop(self) -> None:
        """Health monitor: checks for stale frames every 5s."""
        while self._running:
            time.sleep(HEALTH_CHECK_INTERVAL_S)
            if not self._running:
                break

            now = time.monotonic()
            for key, state in list(self._cameras.items()):
                if state.status != CameraStatus.CONNECTED:
                    continue
                if state.last_frame_time <= 0:
                    continue

                age = now - state.last_frame_time
                if age > STALE_FRAME_THRESHOLD_S:
                    logger.warning(
                        "Camera '%s' stale (%.1fs since last frame) — reconnecting",
                        key,
                        age,
                    )
                    self._try_reconnect(key)

    def _try_reconnect(self, camera_key: str) -> None:
        """Attempt to reconnect a stale camera with exponential backoff."""
        state = self._cameras.get(camera_key)
        if state is None:
            return

        state.reconnect_count += 1
        if state.reconnect_count > MAX_RECONNECT_ATTEMPTS:
            state.status = CameraStatus.ERROR
            state.error = f"Max reconnect attempts ({MAX_RECONNECT_ATTEMPTS}) exceeded"
            logger.error("Camera '%s' max reconnects exceeded", camera_key)
            return

        backoff = RECONNECT_BACKOFF_BASE_S**state.reconnect_count
        logger.info(
            "Camera '%s' reconnect attempt %d/%d (backoff %.1fs)",
            camera_key,
            state.reconnect_count,
            MAX_RECONNECT_ATTEMPTS,
            backoff,
        )

        self.disconnect(camera_key)
        time.sleep(backoff)

        if not self._running:
            return

        ok = self.connect(camera_key)
        if not ok:
            logger.warning("Camera '%s' reconnect attempt failed", camera_key)
