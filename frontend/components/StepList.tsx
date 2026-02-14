"use client";

import { useCallback, useEffect, useRef } from "react";
import { useAssembly } from "@/context/AssemblyContext";
import { useExecution } from "@/context/ExecutionContext";
import { AnalysisPanel } from "./AnalysisPanel";
import { StepCard } from "./StepCard";

export function StepList() {
  const { assembly, selectedStepId, selectStep } = useAssembly();
  const { executionState } = useExecution();
  const listRef = useRef<HTMLDivElement>(null);
  const activeRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to active step during execution
  useEffect(() => {
    if (executionState.phase === "running" && activeRef.current) {
      activeRef.current.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [executionState.currentStepId, executionState.phase]);

  const openUpload = useCallback(() => {
    window.dispatchEvent(new Event("open-upload"));
  }, []);

  if (!assembly || assembly.stepOrder.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center p-6">
        <p className="text-[13px] text-text-tertiary">No assembly loaded</p>
        <button
          onClick={openUpload}
          className="mt-3 text-[12px] font-medium text-signal hover:underline"
        >
          Upload STEP file
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-col" ref={listRef}>
      {/* Panel header */}
      <div className="flex items-center justify-between px-4 pt-3 pb-2">
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-tertiary">
            Assembly Steps
          </span>
          <span className="text-[10px] tabular-nums text-text-tertiary">
            {assembly.stepOrder.length}
          </span>
        </div>
        <button
          onClick={openUpload}
          className="text-[11px] font-medium text-text-secondary transition-colors hover:text-text-primary"
          title="Upload STEP file"
        >
          + Upload
        </button>
      </div>

      <div className="px-4 pb-2">
        <AnalysisPanel />
      </div>

      <div className="flex flex-col">
        {assembly.stepOrder.map((stepId, index) => {
          const step = assembly.steps[stepId];
          if (!step) return null;
          const runtimeState = executionState.stepStates[stepId];
          if (!runtimeState) return null;
          const isActive = executionState.currentStepId === stepId;

          return (
            <div key={stepId} ref={isActive ? activeRef : undefined}>
              <StepCard
                step={step}
                stepIndex={index + 1}
                runtimeState={runtimeState}
                isSelected={selectedStepId === stepId}
                onClick={() => selectStep(stepId)}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}
