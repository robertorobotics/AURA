import type {
  Assembly,
  AssemblySummary,
  Demo,
  ExecutionState,
  HardwareStatus,
  PlanAnalysis,
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
  MOCK_SUMMARIES,
} from "./mock-data";
import { recordingEvents } from "./recording-events";

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

// --- Streaming upload progress types ---

export type UploadProgressEvent =
  | { type: "progress"; stage: string; detail: string; progress: number }
  | { type: "complete"; assembly: Assembly }
  | { type: "error"; detail: string };

/**
 * Upload a STEP file and stream NDJSON progress events.
 * Returns the parsed Assembly once the stream completes.
 */
async function uploadCADStreaming(
  file: File,
  onProgress: (event: UploadProgressEvent) => void,
): Promise<Assembly> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${BASE}/assemblies/upload`, { method: "POST", body: form });

  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `Upload failed: ${res.status}`);
  }
  if (!res.body) throw new Error("No response body for streaming upload");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let assembly: Assembly | null = null;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // Process all complete NDJSON lines in the buffer
    let newlineIdx: number;
    while ((newlineIdx = buffer.indexOf("\n")) !== -1) {
      const line = buffer.slice(0, newlineIdx).trim();
      buffer = buffer.slice(newlineIdx + 1);
      if (!line) continue;

      try {
        const event = JSON.parse(line) as UploadProgressEvent;
        onProgress(event);

        if (event.type === "complete") {
          assembly = event.assembly;
        } else if (event.type === "error") {
          throw new Error(event.detail);
        }
      } catch (e) {
        if (e instanceof SyntaxError) continue; // skip malformed lines
        throw e; // re-throw Error from "error" event
      }
    }
  }

  if (!assembly) throw new Error("Upload stream ended without a result");
  return assembly;
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
  // --- SWR fetchers with mock fallback for offline/demo mode ---
  fetchAssemblySummaries: () =>
    withMockFallback(() => get<AssemblySummary[]>("/assemblies"), MOCK_SUMMARIES),
  fetchAssembly: (id: string) =>
    withMockFallback(
      () => get<Assembly>(`/assemblies/${id}`),
      MOCK_ASSEMBLIES.find((a) => a.id === id) ?? MOCK_ASSEMBLY,
    ),
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
  startAssembly: (id: string, speed?: number, demoMode?: boolean) =>
    post("/execution/start", {
      assembly_id: id,
      speed: speed ?? 1.0,
      demo_mode: demoMode ?? false,
    }),
  pauseExecution: () => post("/execution/pause"),
  resumeExecution: () => post("/execution/resume"),
  stopExecution: () => post("/execution/stop"),
  emergencyStop: () => post("/hardware/estop"),
  intervene: () => post("/execution/intervene"),

  // --- Assembly + step updates ---
  renameAssembly: (id: string, name: string) => patch(`/assemblies/${id}`, { name }),
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

  // --- Hardware ---
  getHardwareStatus: () =>
    withMockFallback(
      () => get<HardwareStatus>("/hardware/status"),
      {
        arms: [], pairings: [], totalArms: 0,
        connected: 0, disconnected: 0, leaders: 0, followers: 0,
      },
    ),
  fetchHardwareStatus: () => get<HardwareStatus>("/hardware/status"),
  connectArm: (armId: string) => post("/hardware/connect", { armId }),
  disconnectArm: (armId: string) => post("/hardware/disconnect", { armId }),

  // --- Homing ---
  startHoming: (armId: string, homePos?: Record<string, number>) =>
    post("/homing/start", { armId, homePos }),
  stopHoming: () => post("/homing/stop"),

  // --- Recording ---
  startRecording: async (stepId: string) => {
    const result = await post(`/recording/step/${stepId}/start`);
    recordingEvents.emit({ type: "started", stepId, startTime: Date.now() });
    return result;
  },
  stopRecording: async () => {
    const result = await post("/recording/stop");
    recordingEvents.emit({ type: "stopped" });
    return result;
  },
  discardRecording: async () => {
    const result = await post("/recording/discard");
    recordingEvents.emit({ type: "discarded" });
    return result;
  },
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
  uploadCADStreaming,

  // --- Delete ---
  deleteAssembly: (id: string) => del(`/assemblies/${id}`),

  // --- AI Analysis ---
  analyzeAssembly: (id: string, apply?: boolean) =>
    post<PlanAnalysis>(
      `/assemblies/${id}/analyze${apply ? "?apply=true" : ""}`,
    ),
};
