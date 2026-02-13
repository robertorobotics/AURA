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
import type {
  ExecutionPhase,
  ExecutionState,
  StepRuntimeState,
} from "@/lib/types";
import { MOCK_EXECUTION_STATE } from "@/lib/mock-data";
import { api } from "@/lib/api";
import { useAssembly } from "./AssemblyContext";
import { useWebSocket } from "./WebSocketContext";

interface ExecutionContextValue {
  executionState: ExecutionState;
  isRunning: boolean;
  startExecution: () => void;
  pauseExecution: () => void;
  resumeExecution: () => void;
  stopExecution: () => void;
  intervene: () => void;
}

const ExecutionContext = createContext<ExecutionContextValue | null>(null);

function makeIdleStepStates(
  stepOrder: string[],
): Record<string, StepRuntimeState> {
  const states: Record<string, StepRuntimeState> = {};
  for (const id of stepOrder) {
    states[id] = {
      stepId: id,
      status: "pending",
      attempt: 1,
      startTime: null,
      endTime: null,
      durationMs: null,
    };
  }
  return states;
}

export function ExecutionProvider({ children }: { children: ReactNode }) {
  const { assembly } = useAssembly();
  const { lastMessage } = useWebSocket();
  const [state, setState] = useState<ExecutionState>(MOCK_EXECUTION_STATE);
  const [wsActive, setWsActive] = useState(false);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const stepIndexRef = useRef(0);

  const clearTimer = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  // ---------------------------------------------------------------
  // WebSocket-driven state updates
  // ---------------------------------------------------------------
  useEffect(() => {
    if (!lastMessage || typeof lastMessage !== "object") return;
    const msg = lastMessage as Record<string, unknown>;
    if (msg.type !== "execution_state") return;

    // WS is delivering real state — disable mock timer
    setWsActive(true);
    clearTimer();

    setState({
      phase: (msg.phase as ExecutionPhase) ?? "idle",
      assemblyId: (msg.assemblyId as string) ?? null,
      currentStepId: (msg.currentStepId as string) ?? null,
      stepStates: (msg.stepStates as Record<string, StepRuntimeState>) ?? {},
      runNumber: (msg.runNumber as number) ?? 0,
      startTime: (msg.startTime as number) ?? null,
      elapsedMs: (msg.elapsedMs as number) ?? 0,
      overallSuccessRate: (msg.overallSuccessRate as number) ?? 0,
    });
  }, [lastMessage, clearTimer]);

  // ---------------------------------------------------------------
  // Mock execution fallback (when WebSocket is unavailable)
  // ---------------------------------------------------------------
  const advanceStep = useCallback(() => {
    if (!assembly) return;
    setState((prev) => {
      const order = assembly.stepOrder;
      const idx = stepIndexRef.current;

      // Complete current step
      const currentId = order[idx];
      if (!currentId) return prev;
      const updatedStates = { ...prev.stepStates };
      const currentState = updatedStates[currentId];
      if (currentState) {
        updatedStates[currentId] = {
          ...currentState,
          status: "success",
          endTime: Date.now(),
          durationMs: Date.now() - (currentState.startTime ?? Date.now()),
        };
      }

      const nextIdx = idx + 1;
      stepIndexRef.current = nextIdx;

      // Check if done
      if (nextIdx >= order.length) {
        clearTimer();
        return {
          ...prev,
          phase: "complete",
          currentStepId: null,
          stepStates: updatedStates,
          elapsedMs: Date.now() - (prev.startTime ?? Date.now()),
        };
      }

      // Start next step
      const nextId = order[nextIdx];
      if (nextId) {
        const nextState = updatedStates[nextId];
        if (nextState) {
          updatedStates[nextId] = {
            ...nextState,
            status: "running",
            startTime: Date.now(),
          };
        }
      }

      return {
        ...prev,
        currentStepId: nextId ?? null,
        stepStates: updatedStates,
        elapsedMs: Date.now() - (prev.startTime ?? Date.now()),
      };
    });
  }, [assembly, clearTimer]);

  // ---------------------------------------------------------------
  // Execution commands (HTTP → backend, local state as optimistic)
  // ---------------------------------------------------------------
  const startExecution = useCallback(() => {
    if (!assembly || assembly.stepOrder.length === 0) return;
    clearTimer();
    stepIndexRef.current = 0;

    api.startAssembly(assembly.id).catch(console.warn);

    // Set optimistic local state (overwritten by WS if connected)
    const firstStepId = assembly.stepOrder[0];
    if (!firstStepId) return;
    const idleStates = makeIdleStepStates(assembly.stepOrder);
    const firstState = idleStates[firstStepId];
    if (firstState) {
      idleStates[firstStepId] = {
        ...firstState,
        status: "running",
        startTime: Date.now(),
      };
    }

    setState({
      phase: "running",
      assemblyId: assembly.id,
      currentStepId: firstStepId,
      stepStates: idleStates,
      runNumber: state.runNumber + 1,
      startTime: Date.now(),
      elapsedMs: 0,
      overallSuccessRate: state.overallSuccessRate,
    });

    // Only start mock timer if WS is not delivering real state
    if (!wsActive) {
      timerRef.current = setInterval(advanceStep, 1500);
    }
  }, [assembly, clearTimer, advanceStep, wsActive, state.runNumber, state.overallSuccessRate]);

  const pauseExecution = useCallback(() => {
    api.pauseExecution().catch(console.warn);
    clearTimer();
    if (!wsActive) {
      setState((prev) => ({ ...prev, phase: "paused" }));
    }
  }, [clearTimer, wsActive]);

  const resumeExecution = useCallback(() => {
    api.resumeExecution().catch(console.warn);
    if (!wsActive) {
      setState((prev) => ({ ...prev, phase: "running" }));
      timerRef.current = setInterval(advanceStep, 1500);
    }
  }, [advanceStep, wsActive]);

  const stopExecution = useCallback(() => {
    api.stopExecution().catch(console.warn);
    clearTimer();
    stepIndexRef.current = 0;
    if (!wsActive) {
      setState((prev) => ({
        ...prev,
        phase: "idle",
        currentStepId: null,
        stepStates: makeIdleStepStates(assembly?.stepOrder ?? []),
        startTime: null,
        elapsedMs: 0,
      }));
    }
  }, [clearTimer, assembly, wsActive]);

  const intervene = useCallback(() => {
    api.intervene().catch(console.warn);
    clearTimer();
    if (!wsActive) {
      setState((prev) => ({ ...prev, phase: "teaching" }));
    }
  }, [clearTimer, wsActive]);

  // Elapsed time ticker (only for mock mode)
  useEffect(() => {
    if (wsActive || state.phase !== "running") return;
    const ticker = setInterval(() => {
      setState((prev) => ({
        ...prev,
        elapsedMs: Date.now() - (prev.startTime ?? Date.now()),
      }));
    }, 1000);
    return () => clearInterval(ticker);
  }, [state.phase, wsActive]);

  // Cleanup on unmount
  useEffect(() => () => clearTimer(), [clearTimer]);

  const value = useMemo<ExecutionContextValue>(
    () => ({
      executionState: state,
      isRunning: state.phase === "running",
      startExecution,
      pauseExecution,
      resumeExecution,
      stopExecution,
      intervene,
    }),
    [state, startExecution, pauseExecution, resumeExecution, stopExecution, intervene],
  );

  return (
    <ExecutionContext.Provider value={value}>
      {children}
    </ExecutionContext.Provider>
  );
}

export function useExecution(): ExecutionContextValue {
  const ctx = useContext(ExecutionContext);
  if (!ctx) throw new Error("useExecution must be used within ExecutionProvider");
  return ctx;
}
