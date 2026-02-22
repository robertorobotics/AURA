"use client";

import type { ArmStatus } from "@/lib/types";
import { ActionButton } from "../ActionButton";

const STATUS_DOT: Record<string, string> = {
  disconnected: "bg-text-tertiary",
  connecting: "bg-status-warning animate-pulse-subtle",
  connected: "bg-status-success",
  error: "bg-status-error",
};

const STATUS_LABEL: Record<string, string> = {
  disconnected: "Disconnected",
  connecting: "Connecting",
  connected: "Connected",
  error: "Error",
};

interface ArmCardProps {
  arm: ArmStatus;
  onConnect: (armId: string) => void;
  onDisconnect: (armId: string) => void;
  onDelete: (armId: string) => void;
  loading: boolean;
}

export function ArmCard({ arm, onConnect, onDisconnect, onDelete, loading }: ArmCardProps) {
  const isConnected = arm.status === "connected";
  const roleBadgeColor =
    arm.role === "leader" ? "bg-signal-light text-signal" : "bg-accent-light text-text-secondary";

  return (
    <div className="rounded-lg border border-bg-tertiary bg-bg-secondary p-3">
      {/* Row 1: name + badges */}
      <div className="flex items-center gap-2">
        <span className="text-[13px] font-medium text-text-primary">{arm.name}</span>
        <span
          className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.04em] ${roleBadgeColor}`}
        >
          {arm.role}
        </span>
        {arm.calibrated && (
          <span className="rounded bg-status-success-bg px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.04em] text-status-success">
            Calibrated
          </span>
        )}
      </div>

      {/* Row 2: details */}
      <div className="mt-1 flex items-center gap-3 text-[11px] text-text-tertiary">
        <span>{arm.motorType}</span>
        <span className="font-mono">{arm.port}</span>
        {arm.structuralDesign && <span>{arm.structuralDesign}</span>}
      </div>

      {/* Row 3: status + actions */}
      <div className="mt-2.5 flex items-center gap-3">
        <div className="flex items-center gap-1.5">
          <div className={`h-1.5 w-1.5 rounded-full ${STATUS_DOT[arm.status] ?? STATUS_DOT.disconnected}`} />
          <span className="text-[10px] font-semibold uppercase tracking-[0.04em] text-text-secondary">
            {STATUS_LABEL[arm.status] ?? "Unknown"}
          </span>
        </div>

        <div className="ml-auto flex items-center gap-1.5">
          {isConnected ? (
            <ActionButton
              variant="secondary"
              className="!px-2.5 !py-1 !text-[11px]"
              onClick={() => onDisconnect(arm.id)}
              disabled={loading}
            >
              Disconnect
            </ActionButton>
          ) : (
            <ActionButton
              variant="primary"
              className="!px-2.5 !py-1 !text-[11px]"
              onClick={() => onConnect(arm.id)}
              disabled={loading}
            >
              Connect
            </ActionButton>
          )}
          <button
            onClick={() => onDelete(arm.id)}
            disabled={loading || isConnected}
            className="rounded-md p-1 text-text-tertiary transition-colors hover:bg-status-error-bg hover:text-status-error disabled:pointer-events-none disabled:opacity-50"
            title="Remove arm"
          >
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <polyline points="3 6 5 6 21 6" />
              <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
            </svg>
          </button>
        </div>
      </div>
    </div>
  );
}
