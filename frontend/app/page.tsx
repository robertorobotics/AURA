"use client";

import { useMemo, useCallback } from "react";
import dynamic from "next/dynamic";
import useSWR, { mutate } from "swr";
import { TopBar } from "@/components/TopBar";
import { BottomBar } from "@/components/BottomBar";
import { StepList } from "@/components/StepList";
import { StepDetail } from "@/components/StepDetail";
import { CameraPiP } from "@/components/CameraPiP";
import { TeachingOverlay } from "@/components/TeachingOverlay";
import { DemoBanner } from "@/components/DemoBanner";
import { useAssembly } from "@/context/AssemblyContext";
import { useExecution } from "@/context/ExecutionContext";
import { useTeaching } from "@/context/TeachingContext";
import { useKeyboardShortcuts } from "@/lib/hooks";
import { api } from "@/lib/api";
import type { TeleopState } from "@/lib/types";

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
  const { isTeaching, stopTeaching } = useTeaching();

  const { data: teleop } = useSWR<TeleopState>(
    "/teleop/state",
    api.getTeleopState,
    { refreshInterval: 3000 },
  );

  const toggleTeleop = useCallback(async () => {
    const isActive = teleop?.active ?? false;
    await mutate("/teleop/state", { active: !isActive, arms: [] }, { revalidate: false });
    try {
      if (isActive) {
        await api.stopTeleop();
      } else {
        await api.startTeleop([]);
      }
      await mutate("/teleop/state");
    } catch {
      await mutate("/teleop/state");
    }
  }, [teleop?.active]);

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
        if (isTeaching) {
          void stopTeaching();
        } else if (executionState.phase !== "idle") {
          stopExecution();
        }
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
      t: () => {
        toggleTeleop();
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
      toggleTeleop,
      isTeaching,
      stopTeaching,
    ],
  );

  useKeyboardShortcuts(handlers);

  return (
    <div className="flex h-screen flex-col">
      <TopBar />
      <DemoBanner />

      <main className="flex min-h-0 flex-1">
        {/* Left: 3D Viewer (70%) */}
        <div
          className="relative h-full w-[70%] transition-shadow duration-300"
          style={
            isTeaching
              ? { boxShadow: "inset 0 0 0 2px #DC2626" }
              : undefined
          }
        >
          <AssemblyViewer />
          <CameraPiP />
          <TeachingOverlay />
        </div>

        {/* Divider */}
        <div className="w-px bg-bg-tertiary" />

        {/* Right: Steps + Detail (30%) */}
        <div className="flex w-[30%] min-w-[300px] flex-col">
          <div className="flex-[55] overflow-y-auto border-b border-bg-tertiary">
            <StepList />
          </div>
          <div className="flex-[45] overflow-y-auto">
            <StepDetail />
          </div>
        </div>
      </main>

      <BottomBar />
    </div>
  );
}
