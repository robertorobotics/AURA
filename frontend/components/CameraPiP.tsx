"use client";

import { useState } from "react";
import { useExecution } from "@/context/ExecutionContext";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export function CameraPiP() {
  const { executionState } = useExecution();
  const [expanded, setExpanded] = useState(false);
  const [streamError, setStreamError] = useState(false);

  if (executionState.phase !== "running" && executionState.phase !== "paused") {
    return null;
  }

  return (
    <button
      onClick={() => setExpanded((e) => !e)}
      className={`absolute bottom-4 left-4 overflow-hidden rounded-lg bg-bg-secondary shadow-md transition-all duration-150 ${
        expanded ? "h-[60%] w-[60%]" : "h-[25%] w-[25%]"
      }`}
    >
      {/* Status dot */}
      <div className="absolute right-2 top-2 z-10 flex items-center gap-1.5">
        <span className={`h-2 w-2 rounded-full ${streamError ? "bg-text-tertiary" : "bg-status-success"}`} />
        <span className="text-[10px] font-medium text-text-tertiary">
          {streamError ? "No feed" : "Live"}
        </span>
      </div>

      {/* Camera tabs */}
      <div className="absolute left-2 top-2 z-10 flex gap-1">
        {["Top", "Side"].map((cam) => (
          <span
            key={cam}
            className="rounded bg-bg-tertiary/80 px-1.5 py-0.5 text-[10px] font-medium text-text-secondary"
          >
            {cam}
          </span>
        ))}
      </div>

      {/* MJPEG stream or fallback placeholder */}
      {streamError ? (
        <div className="flex h-full w-full items-center justify-center bg-bg-tertiary">
          <div className="text-center">
            <svg
              width="24"
              height="24"
              viewBox="0 0 24 24"
              fill="none"
              stroke="#9C9C97"
              strokeWidth="1.5"
              strokeLinecap="round"
              className="mx-auto mb-1"
            >
              <rect x="2" y="5" width="20" height="14" rx="2" />
              <circle cx="12" cy="12" r="3" />
            </svg>
            <span className="text-[11px] text-text-tertiary">Camera Feed</span>
          </div>
        </div>
      ) : (
        <img
          src={`${BASE}/video_feed/top?max_width=320&quality=70&target_fps=15`}
          alt="Camera feed"
          className="h-full w-full object-cover"
          onError={() => setStreamError(true)}
        />
      )}
    </button>
  );
}
