"use client";

import type { AssemblyStep, StepRuntimeState } from "@/lib/types";
import { StatusBadge } from "./StatusBadge";

interface StepCardProps {
  step: AssemblyStep;
  stepIndex: number;
  runtimeState: StepRuntimeState;
  isSelected: boolean;
  onClick: () => void;
}

function StepIndicator({ index, status }: { index: number; status: StepRuntimeState["status"] }) {
  const circle = "flex h-7 w-7 shrink-0 items-center justify-center rounded-full";

  if (status === "success") {
    return (
      <div className={`${circle} bg-status-success`}>
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
          <path d="M4 8L7 11L12 5" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </div>
    );
  }

  if (status === "failed") {
    return (
      <div className={`${circle} bg-status-error`}>
        <svg width="12" height="12" viewBox="0 0 14 14" fill="none">
          <path d="M4 4L10 10M10 4L4 10" stroke="white" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
      </div>
    );
  }

  if (status === "running") {
    return (
      <div className={`${circle} animate-pulse-subtle bg-accent`}>
        <span className="font-mono text-[13px] font-semibold text-white">{index}</span>
      </div>
    );
  }

  if (status === "human") {
    return (
      <div className={`${circle} bg-status-human`}>
        <span className="font-mono text-[13px] font-semibold text-white">{index}</span>
      </div>
    );
  }

  if (status === "retrying") {
    return (
      <div className={`${circle} bg-status-warning`}>
        <span className="font-mono text-[13px] font-semibold text-white">{index}</span>
      </div>
    );
  }

  return (
    <div className={`${circle} border-[1.5px] border-bg-tertiary`}>
      <span className="font-mono text-[13px] font-medium tabular-nums text-text-tertiary">
        {index}
      </span>
    </div>
  );
}

function formatDuration(ms: number): string {
  const seconds = Math.round(ms / 1000);
  return `${(seconds / 60) | 0}:${String(seconds % 60).padStart(2, "0")}`;
}

export function StepCard({ step, stepIndex, runtimeState, isSelected, onClick }: StepCardProps) {
  const handlerLabel =
    step.handler === "primitive"
      ? `primitive \u00B7 ${step.primitiveType ?? "unknown"}`
      : "policy";

  return (
    <button
      onClick={onClick}
      className={`flex w-full items-center gap-3 border-b border-bg-tertiary px-4 py-3 text-left transition-colors hover:bg-bg-secondary/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-signal ${
        isSelected ? "border-l-2 border-l-accent" : "border-l-2 border-l-transparent"
      }`}
    >
      <StepIndicator index={stepIndex} status={runtimeState.status} />

      <div className="flex min-w-0 flex-1 flex-col">
        <span className="truncate text-[14px] font-medium text-text-primary">
          {step.name}
        </span>
        <span className="text-[12px] text-text-secondary">{handlerLabel}</span>
      </div>

      <div className="flex shrink-0 flex-col items-end gap-1">
        <StatusBadge
          status={runtimeState.status}
          retryInfo={
            runtimeState.status === "retrying"
              ? `${runtimeState.attempt}/${step.maxRetries}`
              : undefined
          }
        />
        {runtimeState.durationMs != null && (
          <span className="font-mono text-[11px] text-text-tertiary">
            {formatDuration(runtimeState.durationMs)}
          </span>
        )}
      </div>
    </button>
  );
}
