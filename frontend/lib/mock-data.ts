import type {
  Assembly,
  AssemblySummary,
  ExecutionState,
  PlanAnalysis,
  StepMetrics,
  StepRuntimeState,
} from "./types";

// ---------------------------------------------------------------------------
// Parts with 3D placeholder geometry
// ---------------------------------------------------------------------------

const PARTS: Assembly["parts"] = {
  housing: {
    id: "housing",
    cadFile: null,
    meshFile: null,
    graspPoints: [{ pose: [0, 0.04, 0, 0, 0, 0], approach: [0, -1, 0] }],
    position: [0, 0.02, 0],
    geometry: "box",
    dimensions: [0.08, 0.04, 0.06],
    color: "#B0AEA8",
    layoutPosition: [0.12, 0.02, 0.08],
    layoutRotation: [0, 0, 0],
  },
  bearing: {
    id: "bearing",
    cadFile: null,
    meshFile: null,
    graspPoints: [{ pose: [0, 0.05, 0, 0, 0, 0], approach: [0, -1, 0] }],
    position: [0, 0.05, 0],
    geometry: "cylinder",
    dimensions: [0.015, 0.01],
    color: "#8A8884",
    layoutPosition: [-0.08, 0.005, 0.1],
    layoutRotation: [0, 0, 0],
  },
  fixture: {
    id: "fixture",
    cadFile: null,
    meshFile: null,
    graspPoints: [],
    position: [0, -0.01, 0],
    geometry: "box",
    dimensions: [0.1, 0.02, 0.08],
    color: "#D4D3CF",
    isBase: true,
    layoutPosition: [0, 0.01, 0],
    layoutRotation: [0, 0, 0],
  },
  pin_1: {
    id: "pin_1",
    cadFile: null,
    meshFile: null,
    graspPoints: [{ pose: [-0.025, 0.04, 0, 0, 0, 0], approach: [0, -1, 0] }],
    position: [-0.025, 0.045, 0],
    geometry: "cylinder",
    dimensions: [0.003, 0.015],
    color: "#7A7974",
    layoutPosition: [-0.12, 0.0075, 0.08],
    layoutRotation: [0, 0, 0],
  },
  pin_2: {
    id: "pin_2",
    cadFile: null,
    meshFile: null,
    graspPoints: [{ pose: [0.025, 0.04, 0, 0, 0, 0], approach: [0, -1, 0] }],
    position: [0.025, 0.045, 0],
    geometry: "cylinder",
    dimensions: [0.003, 0.015],
    color: "#7A7974",
    layoutPosition: [0.08, 0.0075, 0.12],
    layoutRotation: [0, 0, 0],
  },
};

// ---------------------------------------------------------------------------
// Assembly steps
// ---------------------------------------------------------------------------

const STEPS: Assembly["steps"] = {
  step_001: {
    id: "step_001",
    name: "Pick housing",
    partIds: ["housing"],
    dependencies: [],
    handler: "primitive",
    primitiveType: "pick",
    primitiveParams: { part_id: "housing", grasp_index: 0 },
    policyId: null,
    successCriteria: { type: "force_threshold", threshold: 0.5 },
    maxRetries: 3,
  },
  step_002: {
    id: "step_002",
    name: "Place housing in fixture",
    partIds: ["housing"],
    dependencies: ["step_001"],
    handler: "primitive",
    primitiveType: "place",
    primitiveParams: { target_pose: [0, 0.02, 0], approach_height: 0.05 },
    policyId: null,
    successCriteria: { type: "classifier", model: "step_002_classifier" },
    maxRetries: 3,
  },
  step_003: {
    id: "step_003",
    name: "Pick bearing",
    partIds: ["bearing"],
    dependencies: ["step_002"],
    handler: "primitive",
    primitiveType: "pick",
    primitiveParams: { part_id: "bearing", grasp_index: 0 },
    policyId: null,
    successCriteria: { type: "force_threshold", threshold: 0.3 },
    maxRetries: 3,
  },
  step_004: {
    id: "step_004",
    name: "Insert bearing",
    partIds: ["bearing", "housing"],
    dependencies: ["step_003"],
    handler: "policy",
    primitiveType: null,
    primitiveParams: null,
    policyId: null,
    successCriteria: { type: "force_signature", pattern: "snap_fit" },
    maxRetries: 3,
  },
  step_005: {
    id: "step_005",
    name: "Press fit pins",
    partIds: ["pin_1", "pin_2"],
    dependencies: ["step_004"],
    handler: "primitive",
    primitiveType: "press_fit",
    primitiveParams: { direction: [0, -1, 0], force_target: 15, max_distance: 0.02 },
    policyId: null,
    successCriteria: { type: "force_threshold", threshold: 15 },
    maxRetries: 2,
  },
};

// ---------------------------------------------------------------------------
// Bearing Housing Assembly
// ---------------------------------------------------------------------------

export const MOCK_ASSEMBLY: Assembly = {
  id: "bearing_housing_v1",
  name: "Bearing Housing v1",
  parts: PARTS,
  steps: STEPS,
  stepOrder: ["step_001", "step_002", "step_003", "step_004", "step_005"],
};

export const MOCK_ASSEMBLIES: Assembly[] = [
  MOCK_ASSEMBLY,
  {
    id: "motor_mount_v1",
    name: "Motor Mount v1",
    parts: {},
    steps: {},
    stepOrder: [],
  },
];

export const MOCK_SUMMARIES: AssemblySummary[] = MOCK_ASSEMBLIES.map((a) => ({
  id: a.id,
  name: a.name,
}));

// ---------------------------------------------------------------------------
// Mock execution state — step 3 active, steps 1-2 complete
// ---------------------------------------------------------------------------

function makeStepState(
  stepId: string,
  status: StepRuntimeState["status"],
  durationMs: number | null = null,
): StepRuntimeState {
  const now = Date.now();
  return {
    stepId,
    status,
    attempt: 1,
    startTime: status !== "pending" ? now - (durationMs ?? 0) : null,
    endTime: status === "success" ? now : null,
    durationMs,
  };
}

export const MOCK_EXECUTION_STATE: ExecutionState = {
  phase: "idle",
  assemblyId: "bearing_housing_v1",
  currentStepId: null,
  stepStates: {
    step_001: makeStepState("step_001", "pending"),
    step_002: makeStepState("step_002", "pending"),
    step_003: makeStepState("step_003", "pending"),
    step_004: makeStepState("step_004", "pending"),
    step_005: makeStepState("step_005", "pending"),
  },
  runNumber: 14,
  startTime: null,
  elapsedMs: 0,
  overallSuccessRate: 0.87,
};

// ---------------------------------------------------------------------------
// Per-step analytics
// ---------------------------------------------------------------------------

function makeRecentRuns(count: number, successRate: number, avgMs: number) {
  return Array.from({ length: count }, (_, i) => ({
    success: Math.random() < successRate,
    durationMs: avgMs + (Math.random() - 0.5) * avgMs * 0.4,
    timestamp: Date.now() - (count - i) * 60_000,
  }));
}

export const MOCK_STEP_METRICS: Record<string, StepMetrics> = {
  step_001: {
    stepId: "step_001",
    successRate: 0.96,
    avgDurationMs: 2800,
    totalAttempts: 48,
    demoCount: 12,
    recentRuns: makeRecentRuns(10, 0.96, 2800),
  },
  step_002: {
    stepId: "step_002",
    successRate: 0.92,
    avgDurationMs: 3200,
    totalAttempts: 45,
    demoCount: 10,
    recentRuns: makeRecentRuns(10, 0.92, 3200),
  },
  step_003: {
    stepId: "step_003",
    successRate: 0.94,
    avgDurationMs: 2500,
    totalAttempts: 42,
    demoCount: 8,
    recentRuns: makeRecentRuns(10, 0.94, 2500),
  },
  step_004: {
    stepId: "step_004",
    successRate: 0.78,
    avgDurationMs: 5400,
    totalAttempts: 38,
    demoCount: 22,
    recentRuns: makeRecentRuns(10, 0.78, 5400),
  },
  step_005: {
    stepId: "step_005",
    successRate: 0.88,
    avgDurationMs: 4100,
    totalAttempts: 35,
    demoCount: 6,
    recentRuns: makeRecentRuns(10, 0.88, 4100),
  },
};

// ---------------------------------------------------------------------------
// Mock AI plan analysis
// ---------------------------------------------------------------------------

export const MOCK_PLAN_ANALYSIS: PlanAnalysis = {
  suggestions: [
    {
      stepId: "step_004",
      field: "handler",
      oldValue: "policy",
      newValue: "primitive",
      reason:
        "Bearing insertion with 0.015m radius has sufficient clearance for a linear_insert primitive with compliance control.",
    },
    {
      stepId: "step_005",
      field: "maxRetries",
      oldValue: "2",
      newValue: "4",
      reason:
        "Press fit operations have higher variance; increasing retries reduces human escalation frequency.",
    },
  ],
  warnings: [
    "Step step_004 has no policy trained yet — consider recording demos before execution.",
  ],
  difficultyScore: 4,
  estimatedTeachingMinutes: 15,
  summary:
    "This is a straightforward 5-step bearing assembly. The heuristic plan is mostly correct. Consider switching the bearing insertion from policy to linear_insert primitive since the tolerance is not tight.",
};
