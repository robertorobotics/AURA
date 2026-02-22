"use client";

import { useEffect, useState } from "react";
import { ArmsTab } from "./ArmsTab";
import { PairingsTab } from "./PairingsTab";
import { CamerasTab } from "./CamerasTab";
import { ToolsTab } from "./ToolsTab";
import { CalibrationTab } from "./CalibrationTab";
import { SystemTab } from "./SystemTab";

type SetupTab = "arms" | "pairings" | "cameras" | "tools" | "calibration" | "system";

const TABS: { key: SetupTab; label: string }[] = [
  { key: "arms", label: "Arms" },
  { key: "pairings", label: "Pairings" },
  { key: "cameras", label: "Cameras" },
  { key: "tools", label: "Tools" },
  { key: "calibration", label: "Calibration" },
  { key: "system", label: "System" },
];

interface SetupModalProps {
  open: boolean;
  onClose: () => void;
}

export function SetupModal({ open, onClose }: SetupModalProps) {
  const [activeTab, setActiveTab] = useState<SetupTab>("arms");

  useEffect(() => {
    if (open) setActiveTab("arms");
  }, [open]);

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex" onClick={onClose}>
      {/* Backdrop */}
      <div className="flex-1 bg-black/20" />

      {/* Slide-over panel */}
      <div
        className="flex h-full w-full max-w-lg flex-col bg-bg-primary shadow-xl animate-slide-in-right"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-bg-tertiary px-6 py-4">
          <h2 className="text-[15px] font-semibold text-text-primary">Setup</h2>
          <button
            onClick={onClose}
            className="rounded-md p-1 text-text-tertiary transition-colors hover:bg-bg-secondary hover:text-text-secondary"
          >
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        {/* Tab bar */}
        <div className="flex border-b border-bg-tertiary px-6">
          {TABS.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`px-3 py-2.5 text-[12px] font-medium transition-colors ${
                activeTab === tab.key
                  ? "border-b-2 border-accent text-text-primary"
                  : "border-b-2 border-transparent text-text-tertiary hover:text-text-secondary"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Tab content */}
        <div className="flex-1 overflow-y-auto px-6 py-4">
          {activeTab === "arms" && <ArmsTab />}
          {activeTab === "pairings" && <PairingsTab />}
          {activeTab === "cameras" && <CamerasTab />}
          {activeTab === "tools" && <ToolsTab />}
          {activeTab === "calibration" && <CalibrationTab />}
          {activeTab === "system" && <SystemTab />}
        </div>
      </div>
    </div>
  );
}
