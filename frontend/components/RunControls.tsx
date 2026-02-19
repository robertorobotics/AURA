"use client";

import { useCallback, useState } from "react";
import { useExecution } from "@/context/ExecutionContext";
import { ActionButton } from "./ActionButton";
import { EstopBanner } from "./EstopBanner";

export function RunControls() {
  const {
    executionState,
    speed,
    setSpeed,
    demoMode,
    setDemoMode,
    startExecution,
    pauseExecution,
    resumeExecution,
    stopExecution,
    emergencyStop,
    intervene,
  } = useExecution();

  const { phase } = executionState;
  const isIdle = phase === "idle" || phase === "complete";
  const isRunning = phase === "running";
  const isPaused = phase === "paused";

  const [estopFired, setEstopFired] = useState(false);

  const handleEstop = useCallback(() => {
    emergencyStop();
    setEstopFired(true);
  }, [emergencyStop]);

  return (
    <>
      <div className="flex items-center gap-2">
        <button
          onClick={() => setDemoMode(!demoMode)}
          disabled={!isIdle}
          className={`flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[11px] font-medium transition-colors ${
            demoMode
              ? "bg-accent-blue/15 text-accent-blue"
              : "bg-bg-secondary text-text-tertiary hover:text-text-secondary"
          } disabled:opacity-40 disabled:cursor-not-allowed`}
          title="Demo mode — auto-advance all steps without policies or demos"
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polygon points="5 3 19 12 5 21 5 3" />
          </svg>
          Demo
        </button>

        <div className="flex items-center gap-1.5">
          <input
            type="range"
            min={0.25}
            max={10}
            step={0.25}
            value={speed}
            onChange={(e) => setSpeed(parseFloat(e.target.value))}
            disabled={!isIdle}
            className="h-1 w-20 cursor-pointer appearance-none rounded-full bg-bg-tertiary accent-accent-blue disabled:opacity-40 disabled:cursor-not-allowed [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-text-secondary"
            title={`Playback speed: ${speed}×`}
          />
          <span className="min-w-[28px] text-right font-mono text-[10px] tabular-nums text-text-tertiary">
            {speed}×
          </span>
        </div>

        <div className="h-6 w-px bg-bg-tertiary" />

        {isRunning ? (
          <span className="inline-flex items-center gap-2 rounded-md bg-status-running px-4 py-2 text-[13px] font-semibold text-white">
            <span className="h-[5px] w-[5px] animate-pulse rounded-full bg-white" />
            Running
          </span>
        ) : isPaused ? (
          <ActionButton variant="primary" onClick={resumeExecution}>
            Resume
          </ActionButton>
        ) : (
          <ActionButton
            variant="primary"
            onClick={startExecution}
            disabled={!isIdle}
          >
            Start
          </ActionButton>
        )}

        <ActionButton
          variant="secondary"
          onClick={pauseExecution}
          disabled={!isRunning}
        >
          Pause
        </ActionButton>

        <ActionButton
          variant="secondary"
          onClick={intervene}
          disabled={!isRunning}
        >
          Intervene
        </ActionButton>

        <ActionButton
          variant="ghost"
          onClick={stopExecution}
          disabled={isIdle}
        >
          Stop
        </ActionButton>

        <div className="ml-2 h-6 w-px bg-bg-tertiary" />

        <ActionButton variant="danger" className="ml-1 font-bold" onClick={handleEstop}>
          E-STOP
        </ActionButton>
      </div>

      <EstopBanner visible={estopFired} onDismiss={() => setEstopFired(false)} />
    </>
  );
}
