"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AreaChart, Area, ResponsiveContainer } from "recharts";
import type { TrainConfig, TrainStatus, TrainingPreset } from "@/lib/types";
import { api } from "@/lib/api";
import { ActionButton } from "./ActionButton";

interface TrainingProgressProps {
  stepId: string;
  assemblyId: string;
  handler: string;
  policyId: string | null;
}

const ARCH_OPTIONS: { value: TrainConfig["architecture"]; label: string }[] = [
  { value: "act", label: "ACT" },
  { value: "diffusion", label: "Diffusion" },
  { value: "pi0", label: "PI0.5 Flow" },
];

export function TrainingProgress({ stepId, assemblyId, handler, policyId }: TrainingProgressProps) {
  const [status, setStatus] = useState<TrainStatus | null>(null);
  const [lossHistory, setLossHistory] = useState<{ step: number; loss: number }[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [arch, setArch] = useState<TrainConfig["architecture"]>("act");
  const [presets, setPresets] = useState<TrainingPreset[]>([]);
  const pollRef = useRef<ReturnType<typeof setInterval>>(null);

  // Load presets on mount
  useEffect(() => {
    void api.getTrainingPresets().then(setPresets);
  }, []);

  // Stop polling on unmount or step change
  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [stepId]);

  const startPolling = useCallback((jobId: string) => {
    setLossHistory([]);
    let pollCount = 0;

    pollRef.current = setInterval(async () => {
      try {
        const s = await api.getTrainingStatus(jobId);
        // Normalize: backend sends "status", frontend expects "state"
        const normalized: TrainStatus = {
          ...s,
          state: normalizeState(s.state ?? (s as Record<string, unknown>).status as string),
        };
        setStatus(normalized);
        pollCount++;
        if (normalized.loss != null) {
          setLossHistory((prev) => [...prev, { step: pollCount, loss: normalized.loss! }]);
        }
        if (normalized.state === "complete" || normalized.state === "failed" || normalized.state === "cancelled") {
          if (pollRef.current) clearInterval(pollRef.current);
          if (normalized.state === "failed") setError("Training failed");
        }
      } catch {
        // Polling error — keep trying
      }
    }, 2000);
  }, []);

  const handleTrain = useCallback(async () => {
    setError(null);
    setStatus(null);
    try {
      const result = await api.trainStep(stepId, {
        architecture: arch,
        numSteps: 10_000,
        assemblyId,
      });
      setStatus(result);
      startPolling(result.jobId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start training");
    }
  }, [stepId, assemblyId, arch, startPolling]);

  const handleCancel = useCallback(async () => {
    if (!status?.jobId) return;
    try {
      await api.cancelTraining(status.jobId);
    } catch {
      // Best effort
    }
  }, [status?.jobId]);

  const handleDeploy = useCallback(async () => {
    try {
      await api.deployPolicy(assemblyId, stepId, "bc");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Deploy failed");
    }
  }, [assemblyId, stepId]);

  if (handler !== "policy") return null;

  const isTraining = status?.state === "queued" || status?.state === "training";
  const isComplete = status?.state === "complete";
  const isCancelled = status?.state === "cancelled";

  return (
    <div className="flex flex-col gap-2">
      {/* Architecture selector */}
      {!isTraining && !isComplete && (
        <div className="flex items-center gap-2">
          <select
            value={arch}
            onChange={(e) => setArch(e.target.value as TrainConfig["architecture"])}
            className="rounded-md border border-border bg-surface-secondary px-2 py-1 text-[12px] text-text-primary"
          >
            {ARCH_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
                {presets.find((p) => p.architecture === opt.value)
                  ? ""
                  : " (unavailable)"}
              </option>
            ))}
          </select>
        </div>
      )}

      {isComplete ? (
        <div className="flex flex-col gap-1.5">
          <div className="flex items-center gap-2">
            <div className="h-2.5 w-2.5 rounded-full bg-status-success" />
            <span className="text-[13px] font-medium text-status-success">Policy trained</span>
            {policyId && (
              <span className="font-mono text-[11px] text-text-tertiary">{policyId}</span>
            )}
          </div>
          <ActionButton
            variant="secondary"
            className="!text-[11px]"
            onClick={() => void handleDeploy()}
          >
            Deploy
          </ActionButton>
        </div>
      ) : (
        <div className="flex items-center gap-2">
          <ActionButton
            variant="primary"
            disabled={isTraining}
            onClick={() => void handleTrain()}
          >
            {isTraining
              ? `Training... ${Math.round((status?.progress ?? 0) * 100)}%`
              : "Train"}
          </ActionButton>
          {isTraining && (
            <ActionButton
              variant="secondary"
              className="!px-2 !py-1 !text-[11px]"
              onClick={() => void handleCancel()}
            >
              Cancel
            </ActionButton>
          )}
        </div>
      )}

      {/* Loss sparkline during training */}
      {isTraining && lossHistory.length > 1 && (
        <div className="h-[40px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={lossHistory} margin={{ top: 0, right: 0, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="lossGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#2574D4" stopOpacity={0.2} />
                  <stop offset="100%" stopColor="#2574D4" stopOpacity={0} />
                </linearGradient>
              </defs>
              <Area
                type="monotone"
                dataKey="loss"
                stroke="#2574D4"
                strokeWidth={1.5}
                fill="url(#lossGradient)"
                isAnimationActive={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}

      {isCancelled && (
        <div className="flex items-center gap-2">
          <p className="text-[11px] text-text-tertiary">Training cancelled</p>
          <ActionButton
            variant="secondary"
            className="!px-2 !py-0.5 !text-[11px]"
            onClick={() => void handleTrain()}
          >
            Retry
          </ActionButton>
        </div>
      )}

      {error && (
        <div className="flex items-center gap-2">
          <p className="text-[11px] text-status-error">{error}</p>
          <ActionButton
            variant="secondary"
            className="!px-2 !py-0.5 !text-[11px]"
            onClick={() => void handleTrain()}
          >
            Retry
          </ActionButton>
        </div>
      )}
    </div>
  );
}

/** Normalize backend status field to frontend state. */
function normalizeState(raw: string): TrainStatus["state"] {
  const map: Record<string, TrainStatus["state"]> = {
    pending: "queued",
    running: "training",
    completed: "complete",
    failed: "failed",
    cancelled: "cancelled",
    // Frontend values pass through
    queued: "queued",
    training: "training",
    complete: "complete",
  };
  return map[raw] ?? "queued";
}
