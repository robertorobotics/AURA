"""API response schemas for execution state and analytics.

These Pydantic models match the TypeScript interfaces in frontend/lib/types.ts.
All use camelCase aliases for JSON serialization.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AssemblySummary(BaseModel):
    """Lightweight assembly reference for list endpoints."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str


class StepRuntimeState(BaseModel):
    """Per-step execution state during a run."""

    model_config = ConfigDict(populate_by_name=True)

    step_id: str = Field(alias="stepId")
    status: str = "pending"
    attempt: int = 1
    start_time: float | None = Field(None, alias="startTime")
    end_time: float | None = Field(None, alias="endTime")
    duration_ms: float | None = Field(None, alias="durationMs")


class ExecutionState(BaseModel):
    """Full sequencer state matching the frontend ExecutionState interface."""

    model_config = ConfigDict(populate_by_name=True)

    phase: str = "idle"
    assembly_id: str | None = Field(None, alias="assemblyId")
    current_step_id: str | None = Field(None, alias="currentStepId")
    step_states: dict[str, StepRuntimeState] = Field(default_factory=dict, alias="stepStates")
    run_number: int = Field(0, alias="runNumber")
    start_time: float | None = Field(None, alias="startTime")
    elapsed_ms: float = Field(0, alias="elapsedMs")
    overall_success_rate: float = Field(0, alias="overallSuccessRate")


class RunEntry(BaseModel):
    """A single run result for step metrics history."""

    model_config = ConfigDict(populate_by_name=True)

    success: bool
    duration_ms: float = Field(alias="durationMs")
    timestamp: float


class StepMetrics(BaseModel):
    """Per-step analytics data."""

    model_config = ConfigDict(populate_by_name=True)

    step_id: str = Field(alias="stepId")
    success_rate: float = Field(0, alias="successRate")
    avg_duration_ms: float = Field(0, alias="avgDurationMs")
    total_attempts: int = Field(0, alias="totalAttempts")
    demo_count: int = Field(0, alias="demoCount")
    recent_runs: list[RunEntry] = Field(default_factory=list, alias="recentRuns")


# ------------------------------------------------------------------
# Teleop schemas
# ------------------------------------------------------------------


class TeleopStartRequest(BaseModel):
    """Request body for starting teleoperation."""

    model_config = ConfigDict(populate_by_name=True)

    arms: list[str] = Field(default_factory=lambda: ["default"])


class TeleopState(BaseModel):
    """Current teleoperation state."""

    model_config = ConfigDict(populate_by_name=True)

    active: bool = False
    arms: list[str] = Field(default_factory=list)
    session_id: str | None = Field(None, alias="sessionId")
    mock: bool = False
    loop_count: int = Field(0, alias="loopCount")


# ------------------------------------------------------------------
# Recording schemas
# ------------------------------------------------------------------


class RecordingStartRequest(BaseModel):
    """Request body for starting a recording session."""

    model_config = ConfigDict(populate_by_name=True)

    assembly_id: str = Field(alias="assemblyId")


class DemoInfo(BaseModel):
    """Metadata about a recorded demonstration."""

    model_config = ConfigDict(populate_by_name=True)

    demo_id: str = Field(alias="demoId")
    assembly_id: str = Field(alias="assemblyId")
    step_id: str = Field(alias="stepId")
    num_frames: int = Field(0, alias="numFrames")
    duration_s: float = Field(0.0, alias="durationS")
    file_path: str = Field("", alias="filePath")
    timestamp: float = 0.0


# ------------------------------------------------------------------
# Training schemas
# ------------------------------------------------------------------


class TrainRequest(BaseModel):
    """Request body for launching step-policy training."""

    model_config = ConfigDict(populate_by_name=True)

    architecture: str = "act"
    num_steps: int = Field(10_000, alias="numSteps")
    assembly_id: str = Field(alias="assemblyId")


class TrainingJobState(BaseModel):
    """State of a training job."""

    model_config = ConfigDict(populate_by_name=True)

    job_id: str = Field(alias="jobId")
    step_id: str = Field(alias="stepId")
    status: str = "pending"
    progress: float = 0.0
    loss: float | None = None
    val_loss: float | None = Field(None, alias="valLoss")
    error: str | None = None
    checkpoint_path: str | None = Field(None, alias="checkpointPath")


# ------------------------------------------------------------------
# Dataset schemas
# ------------------------------------------------------------------


class DatasetDemoInfo(BaseModel):
    """Metadata about a single recorded demonstration."""

    model_config = ConfigDict(populate_by_name=True)

    demo_id: str = Field(alias="demoId")
    num_frames: int = Field(0, alias="numFrames")
    duration_s: float = Field(0.0, alias="durationS")
    has_images: bool = Field(False, alias="hasImages")
    timestamp: float = 0.0
    file_size_bytes: int = Field(0, alias="fileSizeBytes")


class DatasetSummary(BaseModel):
    """Summary of all demos for a step."""

    model_config = ConfigDict(populate_by_name=True)

    assembly_id: str = Field(alias="assemblyId")
    step_id: str = Field(alias="stepId")
    demo_count: int = Field(0, alias="demoCount")
    total_frames: int = Field(0, alias="totalFrames")
    demos: list[DatasetDemoInfo] = Field(default_factory=list)


# ------------------------------------------------------------------
# Policy schemas
# ------------------------------------------------------------------


class PolicyInfoResponse(BaseModel):
    """Metadata about a trained policy checkpoint."""

    model_config = ConfigDict(populate_by_name=True)

    policy_id: str = Field(alias="policyId")
    policy_type: str = Field(alias="policyType")
    checkpoint_path: str = Field(alias="checkpointPath")
    created_at: float = Field(0.0, alias="createdAt")
    architecture: str = "act"


class DeployRequest(BaseModel):
    """Request to deploy a policy for a step."""

    model_config = ConfigDict(populate_by_name=True)

    policy_type: str = Field(alias="policyType")


class TrainingPresetResponse(BaseModel):
    """A training preset configuration."""

    model_config = ConfigDict(populate_by_name=True)

    name: str
    description: str
    architecture: str
    config: dict


# ------------------------------------------------------------------
# AI Planning schemas
# ------------------------------------------------------------------


class PlanSuggestionResponse(BaseModel):
    """A single AI-suggested change to the assembly plan."""

    model_config = ConfigDict(populate_by_name=True)

    step_id: str = Field(alias="stepId")
    field: str
    old_value: Any = Field(alias="oldValue")
    new_value: Any = Field(alias="newValue")
    reason: str


class PlanAnalysisResponse(BaseModel):
    """Full AI analysis of an assembly plan."""

    model_config = ConfigDict(populate_by_name=True)

    suggestions: list[PlanSuggestionResponse] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    difficulty_score: int = Field(5, alias="difficultyScore")
    estimated_teaching_minutes: int = Field(0, alias="estimatedTeachingMinutes")
    summary: str = ""


# ------------------------------------------------------------------
# Hardware schemas
# ------------------------------------------------------------------


class ArmStatus(BaseModel):
    """Status of a single arm in the registry."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    role: str
    motor_type: str = Field(alias="motorType")
    port: str
    enabled: bool = True
    structural_design: str | None = Field(None, alias="structuralDesign")
    calibrated: bool = False
    status: str = "disconnected"


class PairingInfo(BaseModel):
    """A leader-follower pairing."""

    model_config = ConfigDict(populate_by_name=True)

    leader_id: str = Field(alias="leaderId")
    follower_id: str = Field(alias="followerId")
    name: str


class HardwareStatusResponse(BaseModel):
    """Full hardware status: all arms, pairings, and summary counts."""

    model_config = ConfigDict(populate_by_name=True)

    arms: list[ArmStatus]
    pairings: list[PairingInfo]
    total_arms: int = Field(0, alias="totalArms")
    connected: int = 0
    disconnected: int = 0
    leaders: int = 0
    followers: int = 0


class ConnectRequest(BaseModel):
    """Request to connect or disconnect a single arm (legacy body-based)."""

    model_config = ConfigDict(populate_by_name=True)

    arm_id: str = Field(alias="armId")


class AddArmRequest(BaseModel):
    """Request body for adding a new arm to the registry."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    role: str
    motor_type: str = Field(alias="motorType")
    port: str
    enabled: bool = True
    structural_design: str | None = Field(None, alias="structuralDesign")
    config: dict = Field(default_factory=dict)


class UpdateArmRequest(BaseModel):
    """Request body for updating arm properties. All fields optional."""

    model_config = ConfigDict(populate_by_name=True)

    name: str | None = None
    port: str | None = None
    enabled: bool | None = None
    structural_design: str | None = Field(None, alias="structuralDesign")
    config: dict | None = None


class CreatePairingRequest(BaseModel):
    """Request body for creating a leader-follower pairing."""

    model_config = ConfigDict(populate_by_name=True)

    leader_id: str = Field(alias="leaderId")
    follower_id: str = Field(alias="followerId")
    name: str | None = None


class RemovePairingRequest(BaseModel):
    """Request body for removing a pairing."""

    model_config = ConfigDict(populate_by_name=True)

    leader_id: str = Field(alias="leaderId")
    follower_id: str = Field(alias="followerId")


class ScanMotorsRequest(BaseModel):
    """Request body for scanning motors on a specific port."""

    model_config = ConfigDict(populate_by_name=True)

    port: str
    motor_type: str = Field(alias="motorType")
    baud_rates: list[int] | None = Field(None, alias="baudRates")


class PortInfoResponse(BaseModel):
    """A discovered serial port."""

    model_config = ConfigDict(populate_by_name=True)

    port: str
    description: str
    hardware_id: str = Field(alias="hardwareId")
    in_use: bool = Field(False, alias="inUse")


class MotorDiagnosticsResponse(BaseModel):
    """Diagnostics for a single motor on a connected arm."""

    model_config = ConfigDict(populate_by_name=True)

    motor_id: int = Field(alias="motorId")
    name: str
    position: float | None = None
    velocity: float | None = None
    temperature_c: float | None = Field(None, alias="temperatureC")
    current_ma: float | None = Field(None, alias="currentMa")
    voltage_v: float | None = Field(None, alias="voltageV")
    error_flags: int = Field(0, alias="errorFlags")
    error_description: str = Field("", alias="errorDescription")


class DiscoveredMotorResponse(BaseModel):
    """A motor found during a port scan."""

    model_config = ConfigDict(populate_by_name=True)

    motor_id: int = Field(alias="motorId")
    motor_type: str = Field(alias="motorType")
    baud_rate: int = Field(alias="baudRate")
    model_number: int | None = Field(None, alias="modelNumber")


# ------------------------------------------------------------------
# Homing schemas
# ------------------------------------------------------------------


class HomingStartRequest(BaseModel):
    """Request to start homing a follower arm."""

    model_config = ConfigDict(populate_by_name=True)

    arm_id: str = Field(alias="armId")
    home_pos: dict[str, float] | None = Field(None, alias="homePos")
    duration: float = 10.0
    velocity: float = 0.05


# ------------------------------------------------------------------
# Calibration schemas
# ------------------------------------------------------------------


class CalibrationStatusResponse(BaseModel):
    """Calibration profile status for an arm."""

    model_config = ConfigDict(populate_by_name=True)

    arm_id: str = Field(alias="armId")
    has_zeros: bool = Field(False, alias="hasZeros")
    has_ranges: bool = Field(False, alias="hasRanges")
    has_inversions: bool = Field(False, alias="hasInversions")
    has_gravity: bool = Field(False, alias="hasGravity")
    range_discovery_active: bool = Field(False, alias="rangeDiscoveryActive")
    range_discovery_progress: float = Field(0.0, alias="rangeDiscoveryProgress")
    range_discovery_joint: str | None = Field(None, alias="rangeDiscoveryJoint")


class CalibrationProfileResponse(BaseModel):
    """Full calibration profile data."""

    model_config = ConfigDict(populate_by_name=True)

    arm_id: str = Field(alias="armId")
    zeros: dict[str, float] = Field(default_factory=dict)
    ranges: dict[str, dict[str, float]] = Field(default_factory=dict)
    inversions: dict[str, bool] = Field(default_factory=dict)
    gravity: dict[str, list[float]] | None = None


class RangeDiscoveryRequest(BaseModel):
    """Optional parameters for range discovery."""

    model_config = ConfigDict(populate_by_name=True)

    speed: float = 0.1
    duration_per_joint: float = Field(10.0, alias="durationPerJoint")
    joints: list[str] | None = None


# ------------------------------------------------------------------
# RL Training schemas
# ------------------------------------------------------------------


class RLStartRequest(BaseModel):
    """Request body for starting RL fine-tuning."""

    model_config = ConfigDict(populate_by_name=True)

    assembly_id: str = Field(alias="assemblyId")
    max_episodes: int = Field(50, alias="maxEpisodes")
    movement_scale: float = Field(0.5, alias="movementScale")


class RLTrainingState(BaseModel):
    """State of an RL fine-tuning session."""

    model_config = ConfigDict(populate_by_name=True)

    status: str = "idle"
    step_id: str | None = Field(None, alias="stepId")
    episode: int = 0
    total_episodes: int = 0
    success_rate: float = Field(0.0, alias="successRate")
    intervention_rate: float = Field(0.0, alias="interventionRate")
    critic_loss: float = Field(0.0, alias="criticLoss")
    actor_loss: float = Field(0.0, alias="actorLoss")
    buffer_size: int = Field(0, alias="bufferSize")


# ------------------------------------------------------------------
# Upload progress schemas
# ------------------------------------------------------------------


# ------------------------------------------------------------------
# Camera schemas
# ------------------------------------------------------------------


class CameraConfigRequest(BaseModel):
    """Request body for adding/updating a camera configuration."""

    model_config = ConfigDict(populate_by_name=True)

    key: str
    camera_type: str = Field("opencv", alias="cameraType")
    index_or_path: str | int = Field(0, alias="indexOrPath")
    width: int = 640
    height: int = 480
    fps: int = 30
    serial_number_or_name: str = Field("", alias="serialNumberOrName")
    use_depth: bool = Field(False, alias="useDepth")


# ------------------------------------------------------------------
# Upload progress schemas
# ------------------------------------------------------------------


class UploadProgressEvent(BaseModel):
    """A single progress event emitted during STEP upload processing."""

    model_config = ConfigDict(populate_by_name=True)

    type: str  # "progress" | "complete" | "error"
    stage: str | None = None
    detail: str | None = None
    progress: float | None = None
    assembly: dict[str, Any] | None = None


# ------------------------------------------------------------------
# Tool / Trigger schemas
# ------------------------------------------------------------------


class AddToolRequest(BaseModel):
    """Request body for adding a new tool."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    motor_type: str = Field(alias="motorType")
    port: str
    motor_id: int = Field(alias="motorId")
    tool_type: str = Field("custom", alias="toolType")
    enabled: bool = True
    config: dict = Field(default_factory=dict)


class UpdateToolRequest(BaseModel):
    """Request body for updating tool properties. All fields optional."""

    model_config = ConfigDict(populate_by_name=True)

    name: str | None = None
    port: str | None = None
    motor_id: int | None = Field(None, alias="motorId")
    enabled: bool | None = None
    config: dict | None = None


class AddTriggerRequest(BaseModel):
    """Request body for adding a new trigger device."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    trigger_type: str = Field("gpio_switch", alias="triggerType")
    port: str
    pin: int = 0
    active_low: bool = Field(True, alias="activeLow")
    enabled: bool = True


class UpdateTriggerRequest(BaseModel):
    """Request body for updating trigger properties. All fields optional."""

    model_config = ConfigDict(populate_by_name=True)

    name: str | None = None
    port: str | None = None
    pin: int | None = None
    active_low: bool | None = Field(None, alias="activeLow")
    enabled: bool | None = None


class CreateToolPairingRequest(BaseModel):
    """Request body for creating a trigger-to-tool pairing."""

    model_config = ConfigDict(populate_by_name=True)

    trigger_id: str = Field(alias="triggerId")
    tool_id: str = Field(alias="toolId")
    name: str | None = None
    action: str = "toggle"


class RemoveToolPairingRequest(BaseModel):
    """Request body for removing a trigger-to-tool pairing."""

    model_config = ConfigDict(populate_by_name=True)

    trigger_id: str = Field(alias="triggerId")
    tool_id: str = Field(alias="toolId")
