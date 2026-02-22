"use client";

import { useState } from "react";
import useSWR from "swr";
import type { SystemInfo, SystemStatus } from "@/lib/types";
import { api } from "@/lib/api";
import { ActionButton } from "../ActionButton";

const STAT_CLASS = "rounded-lg bg-bg-secondary p-2.5";
const STAT_LABEL = "text-[10px] font-semibold uppercase tracking-[0.06em] text-text-tertiary";
const STAT_VALUE = "font-mono text-[18px] font-medium tabular-nums text-text-primary";

export function SystemTab() {
  const { data: status } = useSWR<SystemStatus>(
    "/system/status",
    api.getSystemStatus,
    { refreshInterval: 5000 },
  );
  const { data: info } = useSWR<SystemInfo>(
    "/system/info",
    api.fetchSystemInfo,
  );

  const [restarting, setRestarting] = useState(false);

  async function handleRestart() {
    if (!confirm("Restart the system? This will disconnect all hardware.")) return;
    setRestarting(true);
    try {
      await api.restartSystem();
    } catch {
      // Server may drop the connection during restart — that's expected.
    }
    // Wait for the server to come back.
    setTimeout(() => setRestarting(false), 3000);
  }

  const phase = status?.phase ?? "unknown";
  const phaseColor =
    phase === "ready"
      ? "bg-status-success-bg text-status-success"
      : phase === "error"
        ? "bg-status-error-bg text-status-error"
        : "bg-status-warning-bg text-status-warning";

  return (
    <div className="flex flex-col gap-4">
      {/* Phase */}
      <div className="flex items-center gap-2">
        <span className={`rounded px-2 py-0.5 text-[11px] font-semibold uppercase ${phaseColor}`}>
          {phase}
        </span>
        {restarting && (
          <span className="text-[11px] text-text-tertiary animate-pulse-subtle">
            Restarting...
          </span>
        )}
      </div>

      {/* Error banner */}
      {status?.error && (
        <div className="rounded-md bg-status-error-bg px-3 py-2">
          <p className="text-[12px] text-status-error">{status.error}</p>
        </div>
      )}

      {/* Stats grid */}
      <div className="grid grid-cols-3 gap-2">
        <div className={STAT_CLASS}>
          <div className={STAT_LABEL}>Arms</div>
          <div className={STAT_VALUE}>
            {status?.connected ?? 0}/{status?.totalArms ?? 0}
          </div>
        </div>
        <div className={STAT_CLASS}>
          <div className={STAT_LABEL}>Cameras</div>
          <div className={STAT_VALUE}>{status?.camerasConnected ?? 0}</div>
        </div>
        <div className={STAT_CLASS}>
          <div className={STAT_LABEL}>Teleop</div>
          <div className={STAT_VALUE}>{status?.teleopActive ? "On" : "Off"}</div>
        </div>
      </div>

      {/* System info */}
      {info && (
        <div className="rounded-lg border border-bg-tertiary bg-bg-secondary p-3">
          <h3 className="mb-2 text-[12px] font-semibold text-text-primary">System Info</h3>
          <div className="grid grid-cols-2 gap-y-1.5 text-[12px]">
            <span className="text-text-tertiary">Version</span>
            <span className="font-mono text-text-primary">{info.version}</span>
            <span className="text-text-tertiary">Mode</span>
            <span className="text-text-primary">{info.mode}</span>
            <span className="text-text-tertiary">Assemblies</span>
            <span className="text-text-primary">{info.assemblies}</span>
            <span className="text-text-tertiary">LeRobot</span>
            <span className={info.lerobotAvailable ? "text-status-success" : "text-text-tertiary"}>
              {info.lerobotAvailable ? "Available" : "Not available"}
            </span>
          </div>
        </div>
      )}

      {/* Restart button */}
      <div className="mt-2">
        <ActionButton
          variant="danger"
          onClick={handleRestart}
          disabled={restarting}
        >
          {restarting ? "Restarting..." : "Restart System"}
        </ActionButton>
      </div>
    </div>
  );
}
