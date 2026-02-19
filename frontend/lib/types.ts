// Type definitions mirroring nextis/assembly/models.py + runtime state

export type StepStatus =
  | "pending"
  | "running"
  | "success"
  | "failed"
  | "human"
  | "retrying";

export type ExecutionPhase =
  | "idle"
  | "running"
  | "paused"
  | "teaching"
  | "error"
  | "complete";

export interface GraspPoint {
  pose: number[];
  approach: number[];
}

export interface Part {
  id: string;
  cadFile: string | null;
  meshFile: string | null;
  graspPoints: GraspPoint[];
  // Frontend-only 3D fields for placeholder rendering
  position?: [number, number, number];
  rotation?: [number, number, number];
  geometry?: "box" | "cylinder" | "sphere" | "disc" | "plate";
  dimensions?: number[];
  /** Face-analysis shape class (shaft, housing, gear_like, plate, block, complex). */
  shapeClass?: string | null;
  /** Percentage of total surface area by face type. */
  faceStats?: Record<string, number> | null;
  color?: string;
  /** Pre-assembly position on work surface (from layout computation). */
  layoutPosition?: [number, number, number];
  /** Euler XYZ rotation for stable resting on work surface. */
  layoutRotation?: [number, number, number];
  /** Whether this part is the base fixture (never animated). */
  isBase?: boolean;
}

export interface SuccessCriteria {
  type: "force_threshold" | "classifier" | "force_signature" | "position";
  threshold?: number;
  model?: string;
  pattern?: string;
}

export interface AssemblyStep {
  id: string;
  name: string;
  partIds: string[];
  dependencies: string[];
  handler: "primitive" | "policy";
  primitiveType: string | null;
  primitiveParams: Record<string, unknown> | null;
  policyId: string | null;
  successCriteria: SuccessCriteria;
  maxRetries: number;
}

export interface AssemblySummary {
  id: string;
  name: string;
}

export interface Assembly {
  id: string;
  name: string;
  parts: Record<string, Part>;
  steps: Record<string, AssemblyStep>;
  stepOrder: string[];
  unitScale?: number;
}

export interface StepRuntimeState {
  stepId: string;
  status: StepStatus;
  attempt: number;
  startTime: number | null;
  endTime: number | null;
  durationMs: number | null;
}

export interface ExecutionState {
  phase: ExecutionPhase;
  assemblyId: string | null;
  currentStepId: string | null;
  stepStates: Record<string, StepRuntimeState>;
  runNumber: number;
  startTime: number | null;
  elapsedMs: number;
  overallSuccessRate: number;
}

export interface StepMetrics {
  stepId: string;
  successRate: number;
  avgDurationMs: number;
  totalAttempts: number;
  demoCount: number;
  recentRuns: { success: boolean; durationMs: number; timestamp: number }[];
}

export interface TrainConfig {
  architecture: "act" | "diffusion" | "smolvla";
  numSteps: number;
}

export interface TrainStatus {
  jobId: string;
  stepId: string;
  progress: number;
  loss: number | null;
  state: "queued" | "training" | "complete" | "failed";
}

export interface Demo {
  id: string;
  stepId: string;
  assemblyId: string;
  timestamp: number;
  durationMs: number;
}

export interface TeleopState {
  active: boolean;
  arms: string[];
}

export interface SystemInfo {
  version: string;
  mode: "mock" | "hardware";
  assemblies: number;
  lerobotAvailable: boolean;
}

export interface PlanSuggestion {
  stepId: string;
  field: string;
  oldValue: string | Record<string, unknown>;
  newValue: string | Record<string, unknown>;
  reason: string;
}

export interface PlanAnalysis {
  suggestions: PlanSuggestion[];
  warnings: string[];
  difficultyScore: number;
  estimatedTeachingMinutes: number;
  summary: string;
}

// Hardware types
export type ConnectionStatus = "disconnected" | "connecting" | "connected" | "error";

export interface ArmStatus {
  id: string;
  name: string;
  role: "leader" | "follower";
  motorType: string;
  port: string;
  enabled: boolean;
  structuralDesign: string | null;
  calibrated: boolean;
  status: ConnectionStatus;
}

export interface PairingInfo {
  leaderId: string;
  followerId: string;
  name: string;
}

export interface HardwareStatus {
  arms: ArmStatus[];
  pairings: PairingInfo[];
  totalArms: number;
  connected: number;
  disconnected: number;
  leaders: number;
  followers: number;
}
