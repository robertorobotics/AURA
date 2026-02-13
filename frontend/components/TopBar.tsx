"use client";

import { useCallback, useEffect, useState } from "react";
import type { Assembly } from "@/lib/types";
import { useAssembly } from "@/context/AssemblyContext";
import { useConnectionStatus } from "@/lib/hooks";
import { useWebSocket } from "@/context/WebSocketContext";
import { RunControls } from "./RunControls";
import { UploadDialog } from "./UploadDialog";

function ConnectionDot() {
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
    <div className="group relative flex items-center">
      <div className={`h-1.5 w-1.5 rounded-full ${dotClass}`} />
      <span className="pointer-events-none absolute left-4 hidden whitespace-nowrap text-[10px] text-text-tertiary group-hover:block">
        {label}
      </span>
    </div>
  );
}

export function TopBar() {
  const { assemblies, assembly, selectAssembly, refreshAssemblies } = useAssembly();
  const [uploadOpen, setUploadOpen] = useState(false);

  // Listen for upload trigger from StepList
  useEffect(() => {
    const handler = () => setUploadOpen(true);
    window.addEventListener("open-upload", handler);
    return () => window.removeEventListener("open-upload", handler);
  }, []);

  const handleUploadSuccess = useCallback(
    (newAssembly: Assembly) => {
      setUploadOpen(false);
      refreshAssemblies();
      selectAssembly(newAssembly.id, newAssembly);
    },
    [refreshAssemblies, selectAssembly],
  );

  return (
    <>
      <header className="flex h-12 shrink-0 items-center justify-between border-b border-bg-tertiary px-6">
        {/* Left: wordmark + assembly selector + connection */}
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-0.5">
            <span className="text-[16px] font-bold tracking-[0.2em] text-text-primary">
              AURA
            </span>
            <span className="text-[16px] text-text-tertiary">&middot;</span>
          </div>
          <select
            value={assembly?.id ?? ""}
            onChange={(e) => selectAssembly(e.target.value)}
            className="appearance-none rounded bg-transparent px-2 py-1 text-[13px] text-text-primary outline-none transition-colors hover:bg-bg-secondary"
          >
            {assemblies.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
          <ConnectionDot />
        </div>

        {/* Right: run controls */}
        <RunControls />
      </header>

      <UploadDialog
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
        onSuccess={handleUploadSuccess}
      />
    </>
  );
}
