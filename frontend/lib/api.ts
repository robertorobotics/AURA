import type {
  Assembly,
  AssemblySummary,
  Demo,
  ExecutionState,
  StepMetrics,
  SystemInfo,
  TeleopState,
  TrainConfig,
  TrainStatus,
  AssemblyStep,
} from "./types";
import {
  MOCK_ASSEMBLIES,
  MOCK_ASSEMBLY,
  MOCK_EXECUTION_STATE,
  MOCK_STEP_METRICS,
} from "./mock-data";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json() as Promise<T>;
}

async function post<T = void>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json() as Promise<T>;
}

async function postFile<T>(path: string, file: File): Promise<T> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${BASE}${path}`, { method: "POST", body: form });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json() as Promise<T>;
}

async function patch<T = void>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json() as Promise<T>;
}

async function del(path: string): Promise<void> {
  const res = await fetch(`${BASE}${path}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
}

// Mock fallback — only catches network errors (TypeError from fetch when
// server is unreachable). HTTP errors (4xx/5xx) propagate normally.
async function withMockFallback<T>(fetcher: () => Promise<T>, fallback: T): Promise<T> {
  try {
    return await fetcher();
  } catch (error) {
    if (error instanceof TypeError) {
      return fallback;
    }
    throw error;
  }
}

export const api = {
  // --- Raw fetchers for SWR (errors propagate to SWR) ---
  fetchAssemblySummaries: () => get<AssemblySummary[]>("/assemblies"),
  fetchAssembly: (id: string) => get<Assembly>(`/assemblies/${id}`),
  fetchHealth: () => get<{ status: string }>("/health"),
  fetchSystemInfo: () => get<SystemInfo>("/system/info"),

  // --- Fallback-wrapped fetchers for imperative calls ---
  getAssemblies: () =>
    withMockFallback(() => get<Assembly[]>("/assemblies"), MOCK_ASSEMBLIES),
  getAssembly: (id: string) =>
    withMockFallback(() => get<Assembly>(`/assemblies/${id}`), MOCK_ASSEMBLY),
  getExecutionState: () =>
    withMockFallback(
      () => get<ExecutionState>("/execution/state"),
      MOCK_EXECUTION_STATE,
    ),
  getStepMetrics: (assemblyId: string) =>
    withMockFallback(
      () => get<StepMetrics[]>(`/analytics/${assemblyId}/steps`),
      Object.values(MOCK_STEP_METRICS),
    ),

  // --- Execution ---
  startAssembly: (id: string, speed?: number) =>
    post("/execution/start", { assembly_id: id, speed: speed ?? 1.0 }),
  pauseExecution: () => post("/execution/pause"),
  resumeExecution: () => post("/execution/resume"),
  stopExecution: () => post("/execution/stop"),
  intervene: () => post("/execution/intervene"),

  // --- Step updates ---
  updateStep: (assemblyId: string, stepId: string, data: Partial<AssemblyStep>) =>
    patch(`/assemblies/${assemblyId}/steps/${stepId}`, data),

  // --- Teleop ---
  startTeleop: (arms: string[]) => post("/teleop/start", { arms }),
  stopTeleop: () => post("/teleop/stop"),
  fetchTeleopState: () => get<TeleopState>("/teleop/state"),
  getTeleopState: () =>
    withMockFallback(
      () => get<TeleopState>("/teleop/state"),
      { active: false, arms: [] },
    ),

  // --- Recording ---
  startRecording: (stepId: string) => post(`/recording/step/${stepId}/start`),
  stopRecording: () => post("/recording/stop"),
  discardRecording: () => post("/recording/discard"),
  getDemos: (assemblyId: string, stepId: string) =>
    withMockFallback(
      () => get<Demo[]>(`/recording/demos/${assemblyId}/${stepId}`),
      [],
    ),
  fetchDemos: (assemblyId: string, stepId: string) =>
    get<Demo[]>(`/recording/demos/${assemblyId}/${stepId}`),
  deleteDemo: (assemblyId: string, stepId: string, demoId: string) =>
    post(`/recording/demos/${assemblyId}/${stepId}/${demoId}/delete`),

  // --- Training ---
  trainStep: (stepId: string, config: TrainConfig) =>
    post<TrainStatus>(`/training/step/${stepId}/train`, config),
  getTrainingStatus: (jobId: string) =>
    get<TrainStatus>(`/training/jobs/${jobId}`),

  // --- Upload ---
  uploadCAD: (file: File) => postFile<Assembly>("/assemblies/upload", file),

  // --- Delete ---
  deleteAssembly: (id: string) => del(`/assemblies/${id}`),
};
