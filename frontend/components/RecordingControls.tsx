"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import useSWR, { useSWRConfig } from "swr";
import { api } from "@/lib/api";
import { ActionButton } from "./ActionButton";

interface RecordingControlsProps {
  stepId: string;
  assemblyId: string;
}

function formatElapsed(ms: number): string {
  const s = Math.floor(ms / 1000);
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
}

export function RecordingControls({ stepId, assemblyId }: RecordingControlsProps) {
  const [active, setActive] = useState(false);
  const [startTime, setStartTime] = useState<number | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval>>(null);
  const { mutate } = useSWRConfig();

  const demosKey = `/recording/demos/${assemblyId}/${stepId}`;
  const { data: demos } = useSWR(demosKey, () => api.getDemos(assemblyId, stepId));
  const demoCount = demos?.length ?? 0;

  // Elapsed timer
  useEffect(() => {
    if (active && startTime) {
      timerRef.current = setInterval(() => {
        setElapsed(Date.now() - startTime);
      }, 1000);
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [active, startTime]);

  // Reset when step changes
  useEffect(() => {
    setActive(false);
    setStartTime(null);
    setElapsed(0);
    setError(null);
  }, [stepId]);

  const handleStart = useCallback(async () => {
    setError(null);
    try {
      await api.startRecording(stepId);
      setActive(true);
      setStartTime(Date.now());
      setElapsed(0);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start recording");
    }
  }, [stepId]);

  const handleStop = useCallback(async () => {
    try {
      await api.stopRecording();
    } catch {
      // Stop may fail if backend is unavailable — still update local state
    }
    setActive(false);
    setStartTime(null);
    void mutate(demosKey);
  }, [demosKey, mutate]);

  const handleDiscard = useCallback(async () => {
    try {
      await api.discardRecording();
    } catch {
      // Discard may fail if backend is unavailable
    }
    setActive(false);
    setStartTime(null);
    void mutate(demosKey);
  }, [demosKey, mutate]);

  return (
    <div>
      {active ? (
        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-2">
            <div className="h-2.5 w-2.5 animate-pulse rounded-full bg-status-error" />
            <span className="text-[13px] font-medium text-status-error">Recording...</span>
            <span className="font-mono text-[13px] tabular-nums text-text-secondary">
              {formatElapsed(elapsed)}
            </span>
          </div>
          <div className="flex gap-2">
            <ActionButton variant="primary" onClick={() => void handleStop()}>
              Stop Recording
            </ActionButton>
            <ActionButton variant="danger" onClick={() => void handleDiscard()}>
              Discard
            </ActionButton>
          </div>
        </div>
      ) : (
        <ActionButton variant="secondary" onClick={() => void handleStart()}>
          Record Demos
        </ActionButton>
      )}

      {error && (
        <p className="mt-1 text-[11px] text-status-error">{error}</p>
      )}

      <p className="mt-1.5 text-[11px] text-text-tertiary">
        {demoCount} demo{demoCount !== 1 ? "s" : ""} recorded
      </p>
    </div>
  );
}
