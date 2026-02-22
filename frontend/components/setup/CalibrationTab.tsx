"use client";

import { useState } from "react";
import useSWR, { mutate } from "swr";
import type { ArmStatus, CalibrationStatus, HardwareStatus } from "@/lib/types";
import { api } from "@/lib/api";
import { ActionButton } from "../ActionButton";

const SWR_HW = "/hardware/status";

function StatusDot({ ok }: { ok: boolean }) {
  return (
    <span
      className={`inline-block h-2 w-2 rounded-full ${ok ? "bg-status-success" : "bg-text-tertiary"}`}
    />
  );
}

function CalibrationArmCard({ arm }: { arm: ArmStatus }) {
  const calKey = `/calibration/${arm.id}/status`;
  const { data: cal } = useSWR<CalibrationStatus>(
    calKey,
    () => api.getCalibrationStatus(arm.id),
    { refreshInterval: arm.status === "connected" ? 2000 : 0 },
  );
  const [loading, setLoading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const isConnected = arm.status === "connected";

  async function run(action: string, fn: () => Promise<unknown>) {
    setLoading(action);
    setError(null);
    try {
      await fn();
      await mutate(calKey);
      await mutate(SWR_HW);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed");
    } finally {
      setLoading(null);
    }
  }

  return (
    <div className="rounded-lg border border-bg-tertiary bg-bg-secondary p-3">
      {/* Header */}
      <div className="flex items-center gap-2">
        <span className="text-[13px] font-medium text-text-primary">{arm.name}</span>
        <span className="rounded bg-bg-tertiary px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-text-secondary">
          {arm.role}
        </span>
        {!isConnected && (
          <span className="text-[10px] text-text-tertiary">disconnected</span>
        )}
      </div>

      {/* Status indicators */}
      <div className="mt-2 flex items-center gap-4 text-[11px] text-text-secondary">
        <span className="flex items-center gap-1">
          <StatusDot ok={cal?.hasZeros ?? false} /> Zeros
        </span>
        <span className="flex items-center gap-1">
          <StatusDot ok={cal?.hasRanges ?? false} /> Ranges
        </span>
        <span className="flex items-center gap-1">
          <StatusDot ok={cal?.hasInversions ?? false} /> Inversions
        </span>
        <span className="flex items-center gap-1">
          <StatusDot ok={cal?.hasGravity ?? false} /> Gravity
        </span>
      </div>

      {/* Range discovery progress */}
      {cal?.rangeDiscoveryActive && (
        <div className="mt-2">
          <div className="flex items-center justify-between text-[10px] text-text-tertiary">
            <span>Discovering: {cal.rangeDiscoveryJoint ?? "..."}</span>
            <span>{Math.round(cal.rangeDiscoveryProgress * 100)}%</span>
          </div>
          <div className="mt-1 h-1 w-full rounded-full bg-bg-tertiary">
            <div
              className="h-1 rounded-full bg-accent transition-all"
              style={{ width: `${cal.rangeDiscoveryProgress * 100}%` }}
            />
          </div>
        </div>
      )}

      {/* Action buttons */}
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        <ActionButton
          variant="secondary"
          className="!px-2 !py-0.5 !text-[10px]"
          disabled={!isConnected || loading !== null}
          onClick={() => run("zero", () => api.recordZeros(arm.id))}
        >
          {loading === "zero" ? "Recording..." : "Record Zeros"}
        </ActionButton>
        <ActionButton
          variant="secondary"
          className="!px-2 !py-0.5 !text-[10px]"
          disabled={!isConnected || loading !== null || (cal?.rangeDiscoveryActive ?? false)}
          onClick={() => run("range", () => api.startRangeDiscovery(arm.id))}
        >
          {cal?.rangeDiscoveryActive ? "Discovering..." : "Discover Ranges"}
        </ActionButton>
        <ActionButton
          variant="primary"
          className="!px-2 !py-0.5 !text-[10px]"
          disabled={!(cal?.hasZeros || cal?.hasRanges) || loading !== null}
          onClick={() => run("apply", () => api.applyCalibration(arm.id))}
        >
          {loading === "apply" ? "Applying..." : "Apply"}
        </ActionButton>
        <ActionButton
          variant="ghost"
          className="!px-2 !py-0.5 !text-[10px]"
          disabled={!(cal?.hasZeros || cal?.hasRanges) || loading !== null}
          onClick={() => {
            if (confirm("Clear all calibration data for this arm?")) {
              run("clear", () => api.clearCalibration(arm.id));
            }
          }}
        >
          Clear
        </ActionButton>
      </div>

      {/* Error */}
      {error && (
        <p className="mt-1.5 text-[10px] text-status-error">{error}</p>
      )}
    </div>
  );
}

export function CalibrationTab() {
  const { data } = useSWR<HardwareStatus>(SWR_HW, api.getHardwareStatus, {
    refreshInterval: 5000,
  });
  const arms = data?.arms ?? [];

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <span className="text-[13px] font-medium text-text-primary">Calibration</span>
        <span className="rounded-full bg-bg-tertiary px-1.5 py-0.5 text-[10px] font-semibold text-text-secondary">
          {arms.length}
        </span>
      </div>

      {arms.map((arm) => (
        <CalibrationArmCard key={arm.id} arm={arm} />
      ))}

      {arms.length === 0 && (
        <p className="py-4 text-center text-[12px] text-text-tertiary">
          No arms configured. Add arms in the Arms tab first.
        </p>
      )}
    </div>
  );
}
