"""SystemState — centralized lifecycle manager for AURA services.

Replaces scattered module-level singletons with a single state object.
Other modules import ``get_state()`` instead of managing their own singletons.
"""

from __future__ import annotations

import enum
import logging
import threading
from typing import TYPE_CHECKING

from nextis.config import CONFIG_PATH, _resolve_config_path, load_config

if TYPE_CHECKING:
    from nextis.cameras.service import CameraService
    from nextis.control.teleop_loop import TeleopLoop
    from nextis.hardware.arm_registry import ArmRegistryService
    from nextis.hardware.calibration import CalibrationManager
    from nextis.learning.recorder import DemoRecorder
    from nextis.tools.registry import ToolRegistryService

logger = logging.getLogger(__name__)


class SystemPhase(enum.StrEnum):
    """Lifecycle phase of the system."""

    UNINITIALIZED = "uninitialized"
    INITIALIZING = "initializing"
    READY = "ready"
    ERROR = "error"
    SHUTTING_DOWN = "shutting_down"


class SystemState:
    """Central state holder for all long-lived services.

    Lifecycle: uninitialized → initializing → ready (or error).
    Call ``initialize()`` once at startup, ``shutdown()`` on exit.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._phase = SystemPhase.UNINITIALIZED
        self._error: str | None = None

        # Eagerly initialized in initialize()
        self._arm_registry: ArmRegistryService | None = None
        self._calibration_manager: CalibrationManager | None = None
        self._camera_service: CameraService | None = None
        self._tool_registry: ToolRegistryService | None = None
        self._config_data: dict = {}

        # Mutable — set by route handlers
        self._teleop_loop: TeleopLoop | None = None
        self._recorder: DemoRecorder | None = None
        self._teleop_session_id: str | None = None
        self._teleop_session_arms: list[str] = []
        self._teleop_session_mock: bool = False

    # --- Read-only properties ---

    @property
    def phase(self) -> SystemPhase:
        """Current lifecycle phase."""
        return self._phase

    @property
    def error(self) -> str | None:
        """Error message if phase is ERROR, else None."""
        return self._error

    @property
    def config_data(self) -> dict:
        """Full parsed config dict (read-only view)."""
        return self._config_data

    @property
    def arm_registry(self) -> ArmRegistryService:
        """Return the ArmRegistryService. Raises if not initialized."""
        if self._arm_registry is None:
            raise RuntimeError("SystemState not initialized — call initialize() first")
        return self._arm_registry

    @property
    def calibration_manager(self) -> CalibrationManager:
        """Return the CalibrationManager. Raises if not initialized."""
        if self._calibration_manager is None:
            raise RuntimeError("SystemState not initialized — call initialize() first")
        return self._calibration_manager

    @property
    def camera_service(self) -> CameraService | None:
        """Active camera service, or ``None`` if no cameras configured."""
        return self._camera_service

    @property
    def tool_registry(self) -> ToolRegistryService | None:
        """Active tool/trigger registry, or ``None`` if not initialized."""
        return self._tool_registry

    # --- Mutable properties (set by route handlers) ---

    @property
    def teleop_loop(self) -> TeleopLoop | None:
        """Active teleop loop, or None."""
        return self._teleop_loop

    @teleop_loop.setter
    def teleop_loop(self, value: TeleopLoop | None) -> None:
        self._teleop_loop = value

    @property
    def recorder(self) -> DemoRecorder | None:
        """Active demo recorder, or None."""
        return self._recorder

    @recorder.setter
    def recorder(self, value: DemoRecorder | None) -> None:
        self._recorder = value

    @property
    def teleop_session_id(self) -> str | None:
        """Current teleop session ID."""
        return self._teleop_session_id

    @teleop_session_id.setter
    def teleop_session_id(self, value: str | None) -> None:
        self._teleop_session_id = value

    @property
    def teleop_session_arms(self) -> list[str]:
        """Arm IDs in the current teleop session."""
        return self._teleop_session_arms

    @teleop_session_arms.setter
    def teleop_session_arms(self, value: list[str]) -> None:
        self._teleop_session_arms = value

    @property
    def teleop_session_mock(self) -> bool:
        """Whether the current teleop session is in mock mode."""
        return self._teleop_session_mock

    @teleop_session_mock.setter
    def teleop_session_mock(self, value: bool) -> None:
        self._teleop_session_mock = value

    # --- Lifecycle ---

    def initialize(self) -> None:
        """Initialize all services in dependency order. Idempotent."""
        with self._lock:
            if self._phase == SystemPhase.READY:
                return
            self._phase = SystemPhase.INITIALIZING

        try:
            self._config_data = load_config()
            self._init_arm_registry()
            self._init_calibration_manager()
            self._init_camera_service()
            self._init_tool_registry()

            with self._lock:
                self._phase = SystemPhase.READY
                self._error = None

            tool_count = len(self._tool_registry.tools) if self._tool_registry else 0
            logger.info(
                "SystemState ready: %d arms, %d pairings, %d tools",
                len(self._arm_registry.arms) if self._arm_registry else 0,
                len(self._arm_registry.pairings) if self._arm_registry else 0,
                tool_count,
            )
        except Exception as exc:
            with self._lock:
                self._phase = SystemPhase.ERROR
                self._error = str(exc)
            logger.error("SystemState initialization failed: %s", exc)

    def _init_arm_registry(self) -> None:
        """Create ArmRegistryService from the resolved config path."""
        from nextis.hardware.arm_registry import ArmRegistryService

        config_path = _resolve_config_path()
        if config_path is not None:
            self._arm_registry = ArmRegistryService(config_path=config_path)
        else:
            # No config file at all — empty registry
            self._arm_registry = ArmRegistryService(config_path=CONFIG_PATH)

    def _init_calibration_manager(self) -> None:
        """Create CalibrationManager for loading/saving calibration profiles."""
        from nextis.config import CALIBRATION_DIR
        from nextis.hardware.calibration import CalibrationManager

        self._calibration_manager = CalibrationManager(config_dir=CALIBRATION_DIR)
        calibrated = self._calibration_manager.list_calibrated()
        if calibrated:
            logger.info("CalibrationManager: %d profiles loaded", len(calibrated))

    def _init_camera_service(self) -> None:
        """Create CameraService from the cameras section of config."""
        from nextis.cameras.service import CameraConfig, CameraService, CameraType

        cameras_cfg = self._config_data.get("cameras") or {}
        if not cameras_cfg:
            logger.info("No cameras configured — skipping CameraService")
            return

        configs: list[CameraConfig] = []
        for key, cam_data in cameras_cfg.items():
            configs.append(
                CameraConfig(
                    key=key,
                    camera_type=CameraType(cam_data.get("type", "opencv")),
                    index_or_path=cam_data.get("index_or_path", cam_data.get("video_device_id", 0)),
                    width=cam_data.get("width", 640),
                    height=cam_data.get("height", 480),
                    fps=cam_data.get("fps", 30),
                    serial_number_or_name=cam_data.get("serial_number_or_name", ""),
                    use_depth=cam_data.get("use_depth", False),
                )
            )

        self._camera_service = CameraService(configs)
        self._camera_service.start()
        logger.info("CameraService initialized with %d cameras", len(configs))

    def _init_tool_registry(self) -> None:
        """Create ToolRegistryService from config data."""
        from nextis.tools.registry import ToolRegistryService

        config_path = _resolve_config_path()
        if config_path is None:
            config_path = CONFIG_PATH
        self._tool_registry = ToolRegistryService(
            config_data=self._config_data,
            config_path=config_path,
        )
        tool_count = len(self._tool_registry.tools)
        trigger_count = len(self._tool_registry.triggers)
        if tool_count or trigger_count:
            logger.info("ToolRegistry: %d tools, %d triggers", tool_count, trigger_count)

    def shutdown(self) -> None:
        """Gracefully shut down all services."""
        with self._lock:
            if self._phase == SystemPhase.SHUTTING_DOWN:
                return
            self._phase = SystemPhase.SHUTTING_DOWN

        if self._teleop_loop is not None:
            try:
                if self._teleop_loop.is_running:
                    self._teleop_loop.stop()
            except Exception as exc:
                logger.error("Error stopping teleop: %s", exc)
            self._teleop_loop = None

        if self._recorder is not None:
            try:
                if self._recorder.is_recording:
                    self._recorder.stop()
            except Exception as exc:
                logger.error("Error stopping recorder: %s", exc)
            self._recorder = None

        if self._camera_service is not None:
            try:
                self._camera_service.shutdown()
            except Exception as exc:
                logger.error("Error shutting down cameras: %s", exc)
            self._camera_service = None

        if self._tool_registry is not None:
            for tool_id in list(self._tool_registry.tool_instances.keys()):
                try:
                    self._tool_registry.disconnect_tool(tool_id)
                except Exception as exc:
                    logger.error("Error disconnecting tool %s: %s", tool_id, exc)
            for trigger_id in list(self._tool_registry.trigger_instances.keys()):
                try:
                    self._tool_registry.disconnect_trigger(trigger_id)
                except Exception as exc:
                    logger.error("Error disconnecting trigger %s: %s", trigger_id, exc)

        if self._arm_registry is not None:
            for arm_id in list(self._arm_registry.arm_instances.keys()):
                try:
                    self._arm_registry.disconnect_arm(arm_id)
                except Exception as exc:
                    logger.error("Error disconnecting arm %s: %s", arm_id, exc)

        self._calibration_manager = None

        with self._lock:
            self._phase = SystemPhase.UNINITIALIZED

        logger.info("SystemState shut down")

    def reload(self) -> None:
        """Shutdown and re-initialize all services."""
        self.shutdown()
        self.initialize()

    # --- Introspection ---

    def get_status_dict(self) -> dict:
        """Return system status for the ``/system/status`` endpoint."""
        status: dict = {
            "phase": self._phase.value,
            "error": self._error,
        }
        if self._arm_registry is not None:
            status.update(self._arm_registry.get_status_summary())
        status["teleopActive"] = self._teleop_loop is not None and self._teleop_loop.is_running
        status["recording"] = self._recorder is not None and self._recorder.is_recording
        status["camerasConnected"] = (
            len(self._camera_service.connected_keys) if self._camera_service else 0
        )
        return status

    def reset_for_testing(self) -> None:
        """Reset all state for test isolation. Not for production use."""
        self._phase = SystemPhase.UNINITIALIZED
        self._error = None
        self._arm_registry = None
        self._calibration_manager = None
        self._camera_service = None
        self._tool_registry = None
        self._config_data = {}
        self._teleop_loop = None
        self._recorder = None
        self._teleop_session_id = None
        self._teleop_session_arms = []
        self._teleop_session_mock = False


# --- Module-level singleton ---

_state: SystemState | None = None
_state_lock = threading.Lock()


def get_state() -> SystemState:
    """Return the global SystemState, initializing on first call."""
    global _state  # noqa: PLW0603
    if _state is None:
        with _state_lock:
            if _state is None:
                _state = SystemState()
                _state.initialize()
    return _state
