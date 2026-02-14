"use client";

import { useCallback, useEffect, useState } from "react";
import type { Assembly } from "@/lib/types";
import { useAssembly } from "@/context/AssemblyContext";
import { useConnectionStatus } from "@/lib/hooks";
import { useWebSocket } from "@/context/WebSocketContext";
import { RunControls } from "./RunControls";
import { UploadDialog } from "./UploadDialog";
import { AssemblySelector } from "./AssemblySelector";

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
  const { selectAssembly, refreshAssemblies } = useAssembly();
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
          <AssemblySelector />
          <button
            onClick={() => setUploadOpen(true)}
            className="flex items-center gap-1.5 rounded-md bg-bg-secondary px-2.5 py-1 text-[12px] font-medium text-text-primary transition-colors hover:bg-bg-tertiary"
            title="Upload STEP file"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
              <polyline points="17 8 12 3 7 8" />
              <line x1="12" y1="3" x2="12" y2="15" />
            </svg>
            Upload
          </button>
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
