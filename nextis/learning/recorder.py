"""Step-segmented demonstration recorder.

Records teleoperation data at 50 Hz into HDF5 files, one file per demo per
step.  Each demo captures ``observation/joint_positions``,
``observation/gripper_state``, ``observation/force_torque``, and
``action/joint_positions`` with assembly/step metadata.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from nextis.errors import RecordingError

logger = logging.getLogger(__name__)

# h5py is optional — fail early with a clear message if missing.
try:
    import h5py

    HAS_H5PY = True
except ImportError:
    h5py = None  # type: ignore[assignment]
    HAS_H5PY = False

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "demos"
RECORDING_HZ = 50


@dataclass
class DemoMetadata:
    """Metadata returned after a recording session completes."""

    demo_id: str
    assembly_id: str
    step_id: str
    file_path: Path
    num_frames: int
    duration_s: float
    timestamp: float = field(default_factory=time.time)


@dataclass
class _Frame:
    """Single timestamped observation frame (internal)."""

    timestamp: float
    joint_positions: dict[str, float]
    gripper_state: float
    force_torque: dict[str, float]
    action_positions: dict[str, float]
    camera_frames: dict[str, np.ndarray] | None = None


class DemoRecorder:
    """Records teleoperation demonstrations for a specific assembly step.

    Captures at 50 Hz in a background thread.  Data is buffered in memory
    and flushed to HDF5 when :meth:`stop` is called.

    Args:
        assembly_id: ID of the assembly being demonstrated.
        step_id: ID of the specific step being demonstrated.
        data_dir: Root directory for demo storage.
    """

    def __init__(
        self,
        assembly_id: str,
        step_id: str,
        data_dir: Path = DEFAULT_DATA_DIR,
        camera_keys: list[str] | None = None,
    ) -> None:
        if not HAS_H5PY:
            raise RecordingError("h5py is required for recording. pip install h5py")

        self._assembly_id = assembly_id
        self._step_id = step_id
        self._data_dir = data_dir

        self._camera_keys = camera_keys or []
        self._frames: list[_Frame] = []
        self._is_recording = False
        self._thread: threading.Thread | None = None
        self._start_time: float = 0.0

        # Generate unique demo id + output path
        self._timestamp = time.time()
        ts_str = time.strftime("%Y%m%d_%H%M%S", time.localtime(self._timestamp))
        self._demo_id = f"demo_{ts_str}"
        self._output_dir = self._data_dir / assembly_id / step_id
        self._file_path = self._output_dir / f"{self._demo_id}.hdf5"

    # -- Properties ----------------------------------------------------------

    @property
    def is_recording(self) -> bool:
        """Whether a recording is currently active."""
        return self._is_recording

    @property
    def demo_id(self) -> str:
        """Unique identifier for this demo session."""
        return self._demo_id

    @property
    def frame_count(self) -> int:
        """Number of frames recorded so far."""
        return len(self._frames)

    # -- Public API ----------------------------------------------------------

    def start(
        self,
        robot_state_fn: Callable[[], dict[str, float]],
        action_fn: Callable[[], dict[str, float]],
        torque_fn: Callable[[], dict[str, float]] | None = None,
        camera_fn: Callable[[str], np.ndarray | None] | None = None,
    ) -> None:
        """Begin recording in a background thread.

        Args:
            robot_state_fn: Returns current robot observation dict.
            action_fn: Returns latest teleop action dict.
            torque_fn: Optional — returns force/torque readings.
            camera_fn: Optional — called with camera_key, returns BGR frame.

        Raises:
            RecordingError: If already recording.
        """
        if self._is_recording:
            raise RecordingError("Recording already in progress")

        self._is_recording = True
        self._start_time = time.monotonic()
        self._frames = []

        self._thread = threading.Thread(
            target=self._record_loop,
            args=(robot_state_fn, action_fn, torque_fn, camera_fn),
            daemon=True,
            name=f"Recorder-{self._step_id}",
        )
        self._thread.start()
        logger.info(
            "Recording started: assembly=%s step=%s demo=%s",
            self._assembly_id,
            self._step_id,
            self._demo_id,
        )

    def stop(self) -> DemoMetadata:
        """Stop recording and flush data to HDF5.

        Returns:
            DemoMetadata with recording statistics.

        Raises:
            RecordingError: If not currently recording.
        """
        if not self._is_recording:
            raise RecordingError("No active recording to stop")

        self._is_recording = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

        duration = time.monotonic() - self._start_time
        self._flush_to_hdf5()

        metadata = DemoMetadata(
            demo_id=self._demo_id,
            assembly_id=self._assembly_id,
            step_id=self._step_id,
            file_path=self._file_path,
            num_frames=len(self._frames),
            duration_s=round(duration, 2),
            timestamp=self._timestamp,
        )
        logger.info(
            "Recording stopped: %d frames, %.1fs -> %s",
            metadata.num_frames,
            metadata.duration_s,
            self._file_path,
        )
        return metadata

    def discard(self) -> None:
        """Stop recording (if active) and delete the output file."""
        if self._is_recording:
            self._is_recording = False
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=2.0)

        if self._file_path.exists():
            self._file_path.unlink()
            logger.info("Discarded recording: %s", self._file_path)

        self._frames = []

    # -- Internal ------------------------------------------------------------

    def _record_loop(
        self,
        robot_state_fn: Callable[[], dict[str, float]],
        action_fn: Callable[[], dict[str, float]],
        torque_fn: Callable[[], dict[str, float]] | None,
        camera_fn: Callable[[str], np.ndarray | None] | None,
    ) -> None:
        """Background capture loop at 50 Hz."""
        dt = 1.0 / RECORDING_HZ

        while self._is_recording:
            loop_start = time.perf_counter()
            try:
                obs = robot_state_fn()
                action = action_fn()
                torques = torque_fn() if torque_fn else {}

                gripper_val = 0.0
                for k, v in obs.items():
                    if "gripper" in k:
                        gripper_val = v
                        break

                # Capture camera frames (ZOH — non-blocking)
                cam_frames: dict[str, np.ndarray] | None = None
                if camera_fn and self._camera_keys:
                    cam_frames = {}
                    for cam_key in self._camera_keys:
                        frame = camera_fn(cam_key)
                        if frame is not None:
                            cam_frames[cam_key] = frame
                    if not cam_frames:
                        cam_frames = None

                self._frames.append(
                    _Frame(
                        timestamp=time.time(),
                        joint_positions=obs,
                        gripper_state=gripper_val,
                        force_torque=torques,
                        action_positions=action,
                        camera_frames=cam_frames,
                    )
                )
            except Exception as e:
                if len(self._frames) % RECORDING_HZ == 0:
                    logger.warning("Recording frame error: %s", e)

            elapsed = time.perf_counter() - loop_start
            time.sleep(max(0, dt - elapsed))

    def _flush_to_hdf5(self) -> None:
        """Write buffered frames to an HDF5 file."""
        if not self._frames:
            logger.warning("No frames to flush")
            return

        self._output_dir.mkdir(parents=True, exist_ok=True)

        joint_keys = sorted(self._frames[0].joint_positions.keys())
        action_keys = sorted(self._frames[0].action_positions.keys())
        torque_keys = (
            sorted(self._frames[0].force_torque.keys()) if self._frames[0].force_torque else []
        )
        n = len(self._frames)

        with h5py.File(str(self._file_path), "w") as f:
            f.attrs["assembly_id"] = self._assembly_id
            f.attrs["step_id"] = self._step_id
            f.attrs["demo_id"] = self._demo_id
            f.attrs["num_frames"] = n
            f.attrs["recording_hz"] = RECORDING_HZ
            f.attrs["timestamp"] = self._timestamp

            f.create_dataset(
                "timestamps",
                data=np.array([fr.timestamp for fr in self._frames]),
            )

            # Observations
            obs_grp = f.create_group("observation")
            jp = np.zeros((n, len(joint_keys)), dtype=np.float32)
            for i, fr in enumerate(self._frames):
                for j, k in enumerate(joint_keys):
                    jp[i, j] = fr.joint_positions.get(k, 0.0)
            obs_grp.create_dataset("joint_positions", data=jp)
            obs_grp.attrs["joint_keys"] = joint_keys

            obs_grp.create_dataset(
                "gripper_state",
                data=np.array([fr.gripper_state for fr in self._frames], dtype=np.float32),
            )

            if torque_keys:
                ft = np.zeros((n, len(torque_keys)), dtype=np.float32)
                for i, fr in enumerate(self._frames):
                    for j, k in enumerate(torque_keys):
                        ft[i, j] = fr.force_torque.get(k, 0.0)
                obs_grp.create_dataset("force_torque", data=ft)
                obs_grp.attrs["torque_keys"] = torque_keys

            # Actions
            act_grp = f.create_group("action")
            ap = np.zeros((n, len(action_keys)), dtype=np.float32)
            for i, fr in enumerate(self._frames):
                for j, k in enumerate(action_keys):
                    ap[i, j] = fr.action_positions.get(k, 0.0)
            act_grp.create_dataset("joint_positions", data=ap)
            act_grp.attrs["joint_keys"] = action_keys

            # Camera images (optional)
            if self._camera_keys and any(fr.camera_frames for fr in self._frames):
                img_grp = f.create_group("observation/images")
                img_grp.attrs["camera_keys"] = self._camera_keys
                for cam_key in self._camera_keys:
                    frames_list: list[np.ndarray] = []
                    last_frame: np.ndarray | None = None
                    for fr in self._frames:
                        if fr.camera_frames and cam_key in fr.camera_frames:
                            last_frame = fr.camera_frames[cam_key]
                        if last_frame is not None:
                            frames_list.append(last_frame)
                    if not frames_list:
                        continue
                    stacked = np.stack(frames_list)
                    h, w = stacked.shape[1], stacked.shape[2]
                    img_grp.create_dataset(
                        cam_key,
                        data=stacked,
                        chunks=(1, h, w, 3),
                        compression="gzip",
                        compression_opts=1,
                    )

        logger.info("Flushed %d frames to %s", n, self._file_path)
