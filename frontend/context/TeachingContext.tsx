"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import useSWR, { useSWRConfig } from "swr";
import { api } from "@/lib/api";
import { useTeleopState, TELEOP_SWR_KEY } from "@/lib/hooks";
import { recordingEvents } from "@/lib/recording-events";
import { useAssembly } from "./AssemblyContext";
import { useExecution } from "./ExecutionContext";

interface TeachingContextValue {
  isTeaching: boolean;
  recordingActive: boolean;
  teleopActive: boolean;
  elapsed: number;
  demoCount: number;
  stepId: string | null;
  stepNumber: number | null;
  stepName: string | null;
  stopTeaching: () => Promise<void>;
  discardTeaching: () => Promise<void>;
}

const TeachingContext = createContext<TeachingContextValue | null>(null);

export function TeachingProvider({ children }: { children: ReactNode }) {
  const { assembly } = useAssembly();
  const { executionState } = useExecution();
  const { mutate } = useSWRConfig();

  // --- Teleop state (shared SWR hook) ---
  const { data: teleop } = useTeleopState();
  const teleopActive = teleop?.active ?? false;

  // --- Recording state (event bus) ---
  const [recordingActive, setRecordingActive] = useState(false);
  const [recordingStepId, setRecordingStepId] = useState<string | null>(null);
  const [startTime, setStartTime] = useState<number | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval>>(null);

  useEffect(() => {
    return recordingEvents.subscribe((event) => {
      if (event.type === "started") {
        setRecordingActive(true);
        setRecordingStepId(event.stepId);
        setStartTime(event.startTime);
        setElapsed(0);
      } else {
        setRecordingActive(false);
        setRecordingStepId(null);
        setStartTime(null);
        setElapsed(0);
      }
    });
  }, []);

  // --- Derived teaching state ---
  const isTeaching =
    (teleopActive && recordingActive) || executionState.phase === "teaching";

  // For execution-driven teaching, use executionState.currentStepId
  const activeStepId = recordingStepId ?? executionState.currentStepId ?? null;

  // --- Elapsed timer ---
  useEffect(() => {
    if (isTeaching && startTime) {
      timerRef.current = setInterval(() => {
        setElapsed(Date.now() - startTime);
      }, 1000);
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [isTeaching, startTime]);

  // --- Demo count ---
  const assemblyId = assembly?.id ?? null;
  const demosKey =
    assemblyId && activeStepId
      ? `/recording/demos/${assemblyId}/${activeStepId}`
      : null;
  const { data: demos } = useSWR(demosKey, () =>
    assemblyId && activeStepId
      ? api.getDemos(assemblyId, activeStepId)
      : Promise.resolve([]),
  );
  const demoCount = demos?.length ?? 0;

  // --- Step info ---
  const stepNumber = useMemo(() => {
    if (!activeStepId || !assembly) return null;
    const idx = assembly.stepOrder.indexOf(activeStepId);
    return idx >= 0 ? idx + 1 : null;
  }, [activeStepId, assembly]);

  const stepName = useMemo(() => {
    if (!activeStepId || !assembly) return null;
    return assembly.steps[activeStepId]?.name ?? null;
  }, [activeStepId, assembly]);

  // --- Actions ---
  const stopTeaching = useCallback(async () => {
    try {
      await api.stopRecording();
    } catch {
      // May fail if backend unavailable
    }
    try {
      await api.stopTeleop();
    } catch {
      // May fail if backend unavailable
    }
    void mutate(TELEOP_SWR_KEY);
    if (demosKey) void mutate(demosKey);
  }, [mutate, demosKey]);

  const discardTeaching = useCallback(async () => {
    try {
      await api.discardRecording();
    } catch {
      // May fail if backend unavailable
    }
    try {
      await api.stopTeleop();
    } catch {
      // May fail if backend unavailable
    }
    void mutate(TELEOP_SWR_KEY);
    if (demosKey) void mutate(demosKey);
  }, [mutate, demosKey]);

  const value = useMemo<TeachingContextValue>(
    () => ({
      isTeaching,
      recordingActive,
      teleopActive,
      elapsed,
      demoCount,
      stepId: activeStepId,
      stepNumber,
      stepName,
      stopTeaching,
      discardTeaching,
    }),
    [
      isTeaching,
      recordingActive,
      teleopActive,
      elapsed,
      demoCount,
      activeStepId,
      stepNumber,
      stepName,
      stopTeaching,
      discardTeaching,
    ],
  );

  return (
    <TeachingContext.Provider value={value}>{children}</TeachingContext.Provider>
  );
}

export function useTeaching(): TeachingContextValue {
  const ctx = useContext(TeachingContext);
  if (!ctx) throw new Error("useTeaching must be used within TeachingProvider");
  return ctx;
}
