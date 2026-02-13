"use client";

import { useCallback, useState } from "react";
import type { Assembly } from "@/lib/types";
import { useAssembly } from "@/context/AssemblyContext";
import { useExecution } from "@/context/ExecutionContext";
import { useConnectionStatus } from "@/lib/hooks";
import { useWebSocket } from "@/context/WebSocketContext";
import { RunControls } from "./RunControls";
import { UploadDialog } from "./UploadDialog";

function formatTime(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function ConnectionIndicator() {
  const { isConnected } = useConnectionStatus();
  const { connectionState } = useWebSocket();

  const isReconnecting = connectionState === "connecting" && !isConnected;

  let dotClass = "bg-status-error";
  let label = "Offline";
  if (isConnected && connectionState === "connected") {
    dotClass = "bg-status-success";
    label = "Connected";
  } else if (isReconnecting) {
    dotClass = "bg-amber-400";
    label = "Reconnecting\u2026";
  }

  return (
    <div className="flex items-center gap-1.5">
      <div className={`h-2 w-2 rounded-full ${dotClass}`} />
      <span className="text-[11px] text-text-tertiary">{label}</span>
    </div>
  );
}

export function TopBar() {
  const { assemblies, assembly, selectAssembly, refreshAssemblies, deleteAssembly } = useAssembly();
  const { executionState } = useExecution();
  const [uploadOpen, setUploadOpen] = useState(false);

  const showTime = executionState.phase !== "idle";
  const timeDisplay = showTime ? formatTime(executionState.elapsedMs) : "--:--";

  const handleUploadSuccess = useCallback(
    (newAssembly: Assembly) => {
      setUploadOpen(false);
      refreshAssemblies();
      selectAssembly(newAssembly.id);
    },
    [refreshAssemblies, selectAssembly],
  );

  const handleDelete = useCallback(() => {
    if (!assembly) return;
    const confirmed = window.confirm(
      `Delete "${assembly.name}"?\n\nThis removes the assembly config and all mesh files.`,
    );
    if (confirmed) {
      void deleteAssembly(assembly.id);
    }
  }, [assembly, deleteAssembly]);

  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-bg-tertiary px-6">
      {/* Left: wordmark + assembly selector + upload + connection status */}
      <div className="flex items-center gap-4">
        <span className="text-[18px] font-semibold tracking-[0.05em] text-accent">
          AURA
        </span>
        <div className="flex items-center gap-1.5">
          <select
            value={assembly?.id ?? ""}
            onChange={(e) => selectAssembly(e.target.value)}
            className="rounded-md border border-bg-tertiary bg-bg-secondary px-3 py-1.5 text-[13px] text-text-primary outline-none focus:ring-2 focus:ring-accent"
          >
            {assemblies.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
          <button
            onClick={() => setUploadOpen(true)}
            className="rounded-md border border-bg-tertiary bg-bg-secondary px-2 py-1.5 text-[13px] text-text-secondary hover:text-text-primary"
          >
            +
          </button>
          <button
            onClick={handleDelete}
            disabled={!assembly}
            className="rounded-md border border-bg-tertiary bg-bg-secondary px-2 py-1.5 text-[13px] text-text-secondary hover:text-red-500 disabled:opacity-30 disabled:pointer-events-none"
            title="Delete assembly"
          >
            &times;
          </button>
        </div>
        <ConnectionIndicator />
      </div>

      <UploadDialog
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
        onSuccess={handleUploadSuccess}
      />

      {/* Center: cycle time */}
      <div className="absolute left-1/2 -translate-x-1/2">
        <span className="font-mono text-[28px] font-semibold tabular-nums text-text-primary">
          {timeDisplay}
        </span>
      </div>

      {/* Right: run controls */}
      <RunControls />
    </header>
  );
}
