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
  geometry?: "box" | "cylinder" | "sphere";
  dimensions?: number[];
  color?: string;
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
