"use client";

import { useState, useCallback } from "react";
import { mutate } from "swr";
import type { TeleopState } from "@/lib/types";
import { api } from "@/lib/api";
import { useTeleopState, TELEOP_SWR_KEY } from "@/lib/hooks";

export function TeleopToggle() {
  const { data: teleop } = useTeleopState();

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const active = teleop?.active ?? false;

  const toggle = useCallback(async () => {
    if (loading) return;
    setLoading(true);
    setError(null);

    const next: TeleopState = active
      ? { active: false, arms: [] }
      : { active: true, arms: [] };

    // Optimistic update
    await mutate(TELEOP_SWR_KEY, next, { revalidate: false });

    try {
      if (active) {
        await api.stopTeleop();
      } else {
        await api.startTeleop([]);
      }
      // Revalidate to get real arm names from server
      await mutate(TELEOP_SWR_KEY);
    } catch {
      // Revert optimistic update
      await mutate(TELEOP_SWR_KEY);
      setError(active ? "Stop failed" : "Start failed");
      setTimeout(() => setError(null), 3000);
    } finally {
      setLoading(false);
    }
  }, [active, loading]);

  if (active) {
    return (
      <div className="flex items-center gap-2">
        <div className="flex flex-col items-center">
          <div className="flex items-center gap-1.5">
            <div className="h-1.5 w-1.5 animate-pulse-subtle rounded-full bg-status-success" />
            <span className="text-[9px] font-medium uppercase tracking-[0.06em] text-text-tertiary leading-none">
              Teleop
            </span>
          </div>
          {teleop?.arms && teleop.arms.length > 0 && (
            <span className="font-mono text-[16px] font-medium tabular-nums leading-tight text-text-primary">
              {teleop.arms.join(", ")}
            </span>
          )}
        </div>
        <button
          onClick={toggle}
          disabled={loading}
          className="rounded-md bg-status-success/10 px-2.5 py-1 text-[11px] font-medium text-status-success transition-colors hover:bg-status-success/20 disabled:opacity-50"
        >
          {loading ? "..." : "Stop Teleop"}
        </button>
        {error && (
          <span className="text-[10px] font-medium text-red-400">{error}</span>
        )}
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <button
        onClick={toggle}
        disabled={loading}
        className="flex items-center gap-1.5 rounded-md px-2.5 py-1 text-[11px] font-medium text-text-tertiary transition-colors hover:bg-bg-tertiary hover:text-text-secondary disabled:opacity-50"
      >
        <svg
          width="12"
          height="12"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M18 11V6a2 2 0 0 0-2-2a2 2 0 0 0-2 2" />
          <path d="M14 10V4a2 2 0 0 0-2-2a2 2 0 0 0-2 2v6" />
          <path d="M10 10.5V6a2 2 0 0 0-2-2a2 2 0 0 0-2 2v8" />
          <path d="M18 8a2 2 0 1 1 4 0v6a8 8 0 0 1-8 8h-2c-2.8 0-4.5-.86-5.99-2.34l-3.6-3.6a2 2 0 0 1 2.83-2.82L7 16" />
        </svg>
        {loading ? "..." : "Start Teleop"}
      </button>
      {error && (
        <span className="text-[10px] font-medium text-red-400">{error}</span>
      )}
    </div>
  );
}
