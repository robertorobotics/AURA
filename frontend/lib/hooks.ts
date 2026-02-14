"use client";

import { useEffect } from "react";
import useSWR from "swr";
import type { TeleopState } from "@/lib/types";
import { api } from "@/lib/api";

type KeyHandler = (e: KeyboardEvent) => void;

export function useKeyboardShortcuts(handlers: Record<string, KeyHandler>) {
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      // Don't trigger shortcuts when typing in inputs
      const target = e.target as HTMLElement;
      if (target.tagName === "INPUT" || target.tagName === "SELECT" || target.tagName === "TEXTAREA") {
        return;
      }

      const handler = handlers[e.key];
      if (handler) {
        handler(e);
      }
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [handlers]);
}

export const TELEOP_SWR_KEY = "/teleop/state";

export function useTeleopState() {
  return useSWR<TeleopState>(TELEOP_SWR_KEY, api.getTeleopState, {
    refreshInterval: 5000,
  });
}

export function useConnectionStatus(): { isConnected: boolean } {
  const { data, error } = useSWR("/health", api.fetchHealth, {
    refreshInterval: 30000,
  });
  return { isConnected: !error && data !== undefined };
}
