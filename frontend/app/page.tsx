"use client";

import { useMemo } from "react";
import dynamic from "next/dynamic";
import { TopBar } from "@/components/TopBar";
import { BottomBar } from "@/components/BottomBar";
import { StepList } from "@/components/StepList";
import { StepDetail } from "@/components/StepDetail";
import { CameraPiP } from "@/components/CameraPiP";
import { TeachingOverlay } from "@/components/TeachingOverlay";
import { DemoBanner } from "@/components/DemoBanner";
import { useAssembly } from "@/context/AssemblyContext";
import { useExecution } from "@/context/ExecutionContext";
import { useKeyboardShortcuts } from "@/lib/hooks";

const AssemblyViewer = dynamic(
  () =>
    import("@/components/viewer/AssemblyViewer").then((m) => ({
      default: m.AssemblyViewer,
    })),
  { ssr: false },
);

export default function DashboardPage() {
  const { assembly, selectedStepId, selectStep } = useAssembly();
  const {
    executionState,
    startExecution,
    pauseExecution,
    resumeExecution,
    stopExecution,
  } = useExecution();

  const handlers = useMemo(
    () => ({
      " ": (e: KeyboardEvent) => {
        e.preventDefault();
        if (executionState.phase === "idle" || executionState.phase === "complete") {
          startExecution();
        } else if (executionState.phase === "running") {
          pauseExecution();
        } else if (executionState.phase === "paused") {
          resumeExecution();
        }
      },
      Escape: () => {
        if (executionState.phase !== "idle") stopExecution();
      },
      ArrowUp: (e: KeyboardEvent) => {
        e.preventDefault();
        if (!assembly) return;
        const order = assembly.stepOrder;
        const idx = selectedStepId ? order.indexOf(selectedStepId) : 0;
        const prev = Math.max(0, idx - 1);
        selectStep(order[prev] ?? null);
      },
      ArrowDown: (e: KeyboardEvent) => {
        e.preventDefault();
        if (!assembly) return;
        const order = assembly.stepOrder;
        const idx = selectedStepId ? order.indexOf(selectedStepId) : -1;
        const next = Math.min(order.length - 1, idx + 1);
        selectStep(order[next] ?? null);
      },
    }),
    [
      assembly,
      selectedStepId,
      selectStep,
      executionState.phase,
      startExecution,
      pauseExecution,
      resumeExecution,
      stopExecution,
    ],
  );

  useKeyboardShortcuts(handlers);

  return (
    <div className="flex h-screen flex-col">
      <TopBar />
      <DemoBanner />

      <main className="flex min-h-0 flex-1">
        {/* Left: 3D Viewer (60%) */}
        <div className="relative w-[60%]">
          <AssemblyViewer />
          <CameraPiP />
        </div>

        {/* Divider */}
        <div className="w-px bg-bg-tertiary" />

        {/* Right: Steps + Detail (40%) */}
        <div className="flex w-[40%] flex-col">
          <div className="flex-[55] overflow-y-auto border-b border-bg-tertiary">
            <StepList />
          </div>
          <div className="flex-[45] overflow-y-auto">
            <StepDetail />
          </div>
        </div>
      </main>

      <BottomBar />

      <TeachingOverlay />
    </div>
  );
}
