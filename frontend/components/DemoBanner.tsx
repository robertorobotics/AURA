"use client";

import useSWR from "swr";
import type { SystemInfo } from "@/lib/types";
import { api } from "@/lib/api";

export function DemoBanner() {
  const { data } = useSWR<SystemInfo>("/system/info", api.fetchSystemInfo, {
    refreshInterval: 30_000,
  });

  // Show banner when mode is mock or when backend is unreachable (data undefined)
  if (data && data.mode !== "mock") return null;

  return (
    <div className="flex h-6 shrink-0 items-center justify-center bg-amber-100">
      <span className="text-[10px] font-medium text-amber-800">
        Demo Mode — no hardware connected
      </span>
    </div>
  );
}
