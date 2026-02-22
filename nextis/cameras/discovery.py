"""Camera device discovery — v4l2 enumeration + RealSense serial listing.

Provides ``discover_cameras()`` which returns a list of available camera
devices without opening persistent connections.
"""

from __future__ import annotations

import glob
import logging
import platform
import struct
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Optional imports
try:
    import pyrealsense2 as rs

    HAS_REALSENSE = True
except ImportError:
    rs = None  # type: ignore[assignment]
    HAS_REALSENSE = False

IS_LINUX = platform.system() == "Linux"


@dataclass
class DiscoveredCamera:
    """A camera device found during discovery.

    Attributes:
        device_path: OS device path (e.g. "/dev/video0") or RealSense serial.
        name: Human-readable name from v4l2/sysfs or RealSense descriptor.
        camera_type: ``"opencv"`` or ``"intelrealsense"``.
        is_realsense: Whether this is an Intel RealSense device.
    """

    device_path: str
    name: str
    camera_type: str
    is_realsense: bool = False


def discover_cameras(
    skip_devices: set[str] | None = None,
    opencv_only: bool = False,
) -> list[DiscoveredCamera]:
    """Enumerate available camera devices.

    Scans ``/dev/video*`` devices (Linux) using v4l2 ioctls to filter for
    real capture devices. Then optionally discovers Intel RealSense cameras
    if ``pyrealsense2`` is available.

    Args:
        skip_devices: Device paths to exclude from results.
        opencv_only: If ``True``, skip RealSense SDK discovery.

    Returns:
        List of :class:`DiscoveredCamera` sorted by device path.
    """
    skip = skip_devices or set()
    results: list[DiscoveredCamera] = []

    if IS_LINUX:
        results.extend(_discover_v4l2(skip))
    else:
        results.extend(_discover_opencv_probe(skip))

    if not opencv_only:
        results.extend(_discover_realsense())

    return results


def _discover_v4l2(skip_devices: set[str]) -> list[DiscoveredCamera]:
    """Enumerate ``/dev/video*`` using v4l2 ioctl ``VIDIOC_QUERYCAP``.

    Filters for devices with ``V4L2_CAP_VIDEO_CAPTURE`` and verifies
    with an OpenCV test read. Skips RealSense UVC nodes (detected via
    sysfs name).
    """
    import fcntl

    VIDIOC_QUERYCAP = 0x80685600  # noqa: N806
    V4L2_CAP_VIDEO_CAPTURE = 0x00000001  # noqa: N806

    ports = sorted(glob.glob("/dev/video*"))
    results: list[DiscoveredCamera] = []

    for port in ports:
        if port in skip_devices:
            continue

        # --- v4l2 capability check ---
        try:
            with open(port, "rb") as fd:
                buf = bytearray(104)
                fcntl.ioctl(fd, VIDIOC_QUERYCAP, buf)
                caps = struct.unpack_from("I", buf, 84)[0]
                if not (caps & V4L2_CAP_VIDEO_CAPTURE):
                    continue
        except (OSError, PermissionError):
            continue

        # --- Sysfs name check — skip RealSense infrared/depth nodes ---
        video_index = port.replace("/dev/video", "")
        sysfs_name = _read_sysfs_name(video_index)
        if sysfs_name and "RealSense" in sysfs_name:
            continue

        # --- Quick OpenCV verification ---
        if not _opencv_test_read(port):
            continue

        name = sysfs_name or f"Camera {port}"
        results.append(
            DiscoveredCamera(
                device_path=port,
                name=name,
                camera_type="opencv",
            )
        )

    return results


def _discover_opencv_probe(skip_devices: set[str]) -> list[DiscoveredCamera]:
    """Fallback for non-Linux: probe integer indices 0-9 via OpenCV."""
    results: list[DiscoveredCamera] = []

    try:
        import cv2
    except ImportError:
        logger.warning("OpenCV not installed — cannot probe cameras")
        return results

    for idx in range(10):
        if str(idx) in skip_devices:
            continue
        cap = cv2.VideoCapture(idx)
        if cap.isOpened():
            ret, _ = cap.read()
            cap.release()
            if ret:
                results.append(
                    DiscoveredCamera(
                        device_path=str(idx),
                        name=f"Camera {idx}",
                        camera_type="opencv",
                    )
                )
        else:
            cap.release()

    return results


def _discover_realsense() -> list[DiscoveredCamera]:
    """Enumerate Intel RealSense cameras via ``pyrealsense2``.

    Returns one entry per unique serial number.
    """
    if not HAS_REALSENSE:
        return []

    results: list[DiscoveredCamera] = []
    try:
        ctx = rs.context()
        devices = ctx.query_devices()
        for dev in devices:
            serial = dev.get_info(rs.camera_info.serial_number)
            name = dev.get_info(rs.camera_info.name)
            results.append(
                DiscoveredCamera(
                    device_path=serial,
                    name=name,
                    camera_type="intelrealsense",
                    is_realsense=True,
                )
            )
    except Exception as exc:
        logger.error("Error scanning RealSense devices: %s", exc)

    return results


def _read_sysfs_name(video_index: str) -> str | None:
    """Read ``/sys/class/video4linux/video{N}/name`` for the device name."""
    try:
        path = f"/sys/class/video4linux/video{video_index}/name"
        with open(path) as f:
            return f.read().strip()
    except (OSError, FileNotFoundError):
        return None


def _opencv_test_read(device_path: str) -> bool:
    """Open a device with OpenCV and attempt a single frame read."""
    try:
        import cv2

        cap = cv2.VideoCapture(device_path)
        if not cap.isOpened():
            cap.release()
            return False
        ret, _ = cap.read()
        cap.release()
        return ret
    except Exception:
        return False
