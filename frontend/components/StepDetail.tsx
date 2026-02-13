"use client";

import useSWR from "swr";
import { useAssembly } from "@/context/AssemblyContext";
import { useExecution } from "@/context/ExecutionContext";
import { MOCK_STEP_METRICS } from "@/lib/mock-data";
import type { StepMetrics } from "@/lib/types";
import { api } from "@/lib/api";
import { ActionButton } from "./ActionButton";
import { StatusBadge } from "./StatusBadge";
import { MiniChart } from "./MiniChart";
import { RecordingControls } from "./RecordingControls";
import { DemoList } from "./DemoList";
import { TrainingProgress } from "./TrainingProgress";

function formatMs(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

export function StepDetail() {
  const { assembly, selectedStepId } = useAssembly();
  const { executionState } = useExecution();

  const { data: allMetrics } = useSWR<StepMetrics[]>(
    assembly ? `/analytics/${assembly.id}/steps` : null,
    () => api.getStepMetrics(assembly!.id),
    { fallbackData: Object.values(MOCK_STEP_METRICS) },
  );

  if (!assembly || !selectedStepId) {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <p className="text-[13px] text-text-tertiary">
          Select a step to view details
        </p>
      </div>
    );
  }

  const step = assembly.steps[selectedStepId];
  if (!step) return null;
  const runtimeState = executionState.stepStates[selectedStepId];
  const metrics = allMetrics?.find((m) => m.stepId === selectedStepId);

  return (
    <div className="flex flex-col gap-4 overflow-y-auto p-4">
      {/* Header */}
      <div>
        <div className="flex items-center justify-between">
          <h2 className="text-[14px] font-semibold text-text-primary">
            {step.name}
          </h2>
          {runtimeState && <StatusBadge status={runtimeState.status} />}
        </div>

        <div className="mt-1 flex items-center gap-2 text-[12px] text-text-secondary">
          <span className="rounded bg-bg-secondary px-1.5 py-0.5 font-medium">
            {step.handler}
          </span>
          {step.primitiveType && (
            <span className="text-text-tertiary">{step.primitiveType}</span>
          )}
          {step.handler === "policy" && (
            <span className="text-text-tertiary">
              {step.policyId ?? "no policy trained"}
            </span>
          )}
        </div>
      </div>

      {/* Success criteria — card style */}
      <div className="rounded-lg bg-bg-secondary p-2.5">
        <span className="text-[10px] font-semibold uppercase tracking-[0.06em] text-text-tertiary">
          Success Criteria
        </span>
        <p className="mt-1 text-[12px] text-text-secondary">
          {step.successCriteria.type.replace(/_/g, " ")}
          {step.successCriteria.threshold != null &&
            ` (threshold: ${step.successCriteria.threshold})`}
          {step.successCriteria.pattern &&
            ` \u2014 ${step.successCriteria.pattern}`}
        </p>
      </div>

      {/* Metrics */}
      {metrics && (
        <div className="grid grid-cols-3 gap-3">
          <div className="rounded-lg bg-bg-secondary p-2.5">
            <span className="text-[10px] font-semibold uppercase tracking-[0.06em] text-text-tertiary">
              Success Rate
            </span>
            <p className="font-mono text-[22px] font-medium tabular-nums text-text-primary">
              {Math.round(metrics.successRate * 100)}%
            </p>
          </div>
          <div className="rounded-lg bg-bg-secondary p-2.5">
            <span className="text-[10px] font-semibold uppercase tracking-[0.06em] text-text-tertiary">
              Avg Duration
            </span>
            <p className="font-mono text-[22px] font-medium tabular-nums text-text-primary">
              {formatMs(metrics.avgDurationMs)}
            </p>
          </div>
          <div className="rounded-lg bg-bg-secondary p-2.5">
            <span className="text-[10px] font-semibold uppercase tracking-[0.06em] text-text-tertiary">
              Demos
            </span>
            <p className="font-mono text-[22px] font-medium tabular-nums text-text-primary">
              {metrics.demoCount}
            </p>
          </div>
        </div>
      )}

      {/* Mini success rate chart */}
      {metrics && <MiniChart runs={metrics.recentRuns} />}

      {/* Recording controls */}
      <RecordingControls stepId={selectedStepId} assemblyId={assembly.id} />

      {/* Demo list */}
      <DemoList assemblyId={assembly.id} stepId={selectedStepId} />

      {/* Training progress */}
      <TrainingProgress
        stepId={selectedStepId}
        handler={step.handler}
        policyId={step.policyId}
      />

      {/* Test step */}
      <ActionButton
        variant="secondary"
        onClick={() => console.log("Test step:", selectedStepId)}
      >
        Test Step
      </ActionButton>
    </div>
  );
}
