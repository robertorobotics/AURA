"use client";

import { Fragment } from "react";
import useSWR from "swr";
import { useAssembly } from "@/context/AssemblyContext";
import { useExecution } from "@/context/ExecutionContext";
import type { HardwareStatus, TeleopState } from "@/lib/types";
import { api } from "@/lib/api";

function formatTime(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function HardwareIndicator() {
  const { data: hw } = useSWR<HardwareStatus>(
    "/hardware/status",
    api.getHardwareStatus,
    { refreshInterval: 5000 },
  );

  if (!hw || hw.totalArms === 0) return null;

  const dotColor =
    hw.connected === hw.totalArms
      ? "bg-status-success"
      : hw.connected > 0
        ? "bg-amber-400"
        : "bg-text-tertiary";

  return (
    <div className="flex flex-col items-center">
      <div className="flex items-center gap-1.5">
        <div className={`h-1.5 w-1.5 rounded-full ${dotColor}`} />
        <span className="text-[9px] font-medium uppercase tracking-[0.06em] text-text-tertiary leading-none">
          Arms
        </span>
      </div>
      <span className="font-mono text-[16px] font-medium tabular-nums leading-tight text-text-primary">
        {hw.connected}/{hw.totalArms}
      </span>
    </div>
  );
}

function TeleopIndicator() {
  const { data: teleop } = useSWR<TeleopState>(
    "/teleop/state",
    api.getTeleopState,
    { refreshInterval: 3000 },
  );

  if (!teleop?.active) return null;

  return (
    <div className="flex flex-col items-center">
      <div className="flex items-center gap-1.5">
        <div className="h-1.5 w-1.5 animate-pulse-subtle rounded-full bg-status-success" />
        <span className="text-[9px] font-medium uppercase tracking-[0.06em] text-text-tertiary leading-none">
          Teleop
        </span>
      </div>
      <span className="font-mono text-[16px] font-medium tabular-nums leading-tight text-text-primary">
        {teleop.arms.join(", ")}
      </span>
    </div>
  );
}

export function BottomBar() {
  const { assembly } = useAssembly();
  const { executionState } = useExecution();

  const completedSteps = Object.values(executionState.stepStates).filter(
    (s) => s.status === "success",
  ).length;
  const totalSteps = assembly?.stepOrder.length ?? 0;

  const items = [
    { label: "Cycle", value: formatTime(executionState.elapsedMs) },
    { label: "Success", value: `${Math.round(executionState.overallSuccessRate * 100)}%` },
    { label: "Steps", value: `${completedSteps} / ${totalSteps}` },
    { label: "Run", value: `#${executionState.runNumber}` },
  ];

  return (
    <footer className="flex h-10 shrink-0 items-center justify-center gap-6 border-t border-bg-tertiary px-6">
      <HardwareIndicator />
      <TeleopIndicator />
      {items.map((item, i) => (
        <Fragment key={item.label}>
          {i === 0 && <div className="h-5 w-px bg-bg-tertiary" />}
          <div className="flex flex-col items-center">
            <span className="text-[9px] font-medium uppercase tracking-[0.06em] text-text-tertiary leading-none">
              {item.label}
            </span>
            <span className="font-mono text-[16px] font-medium tabular-nums leading-tight text-text-primary">
              {item.value}
            </span>
          </div>
          {i < items.length - 1 && <div className="h-5 w-px bg-bg-tertiary" />}
        </Fragment>
      ))}
    </footer>
  );
}
