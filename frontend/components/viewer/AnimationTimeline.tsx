"use client";

import { useCallback, useEffect, useRef, useState } from "react";

const DOT_THRESHOLD = 20;

/** Clickable reference points for large assemblies: first, last, every 10th step. */
function computeMilestones(totalSteps: number): number[] {
  if (totalSteps <= 1) return [0];
  const ms = new Set<number>();
  ms.add(0);
  ms.add(totalSteps - 1);
  for (let i = 9; i < totalSteps; i += 10) ms.add(i);
  return Array.from(ms).sort((a, b) => a - b);
}

interface AnimationTimelineProps {
  totalSteps: number;
  scrubberProgressRef: React.RefObject<number>;
  onScrub: (normalizedT: number) => void;
  onScrubStart: () => void;
  onScrubEnd: () => void;
}

export function AnimationTimeline({
  totalSteps,
  scrubberProgressRef,
  onScrub,
  onScrubStart,
  onScrubEnd,
}: AnimationTimelineProps) {
  const trackRef = useRef<HTMLDivElement>(null);
  const handleRef = useRef<HTMLDivElement>(null);
  const fillRef = useRef<HTMLDivElement>(null);
  const counterRef = useRef<HTMLSpanElement>(null);
  const [dragging, setDragging] = useState(false);

  // 60fps handle + fill + counter sync via rAF (no React re-renders)
  useEffect(() => {
    let raf: number;
    function tick() {
      const progress = scrubberProgressRef.current ?? 0;
      const pct = `${progress * 100}%`;
      if (handleRef.current) handleRef.current.style.left = pct;
      if (fillRef.current) fillRef.current.style.width = pct;
      if (counterRef.current) {
        const step = Math.min(Math.floor(progress * totalSteps) + 1, totalSteps);
        counterRef.current.textContent = `${step}/${totalSteps}`;
      }
      raf = requestAnimationFrame(tick);
    }
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [scrubberProgressRef, totalSteps]);

  const computeT = useCallback((clientX: number) => {
    if (!trackRef.current) return 0;
    const rect = trackRef.current.getBoundingClientRect();
    return Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
  }, []);

  const handlePointerDown = useCallback(
    (e: React.PointerEvent) => {
      e.preventDefault();
      (e.target as HTMLElement).setPointerCapture(e.pointerId);
      setDragging(true);
      onScrubStart();
      onScrub(computeT(e.clientX));
    },
    [onScrubStart, onScrub, computeT],
  );

  const handlePointerMove = useCallback(
    (e: React.PointerEvent) => {
      if (!dragging) return;
      onScrub(computeT(e.clientX));
    },
    [dragging, onScrub, computeT],
  );

  const handlePointerUp = useCallback(() => {
    setDragging(false);
    onScrubEnd();
  }, [onScrubEnd]);

  const handleDotClick = useCallback(
    (index: number) => {
      const t = totalSteps > 1 ? index / (totalSteps - 1) : 0;
      onScrubStart();
      onScrub(t);
      onScrubEnd();
    },
    [totalSteps, onScrub, onScrubStart, onScrubEnd],
  );

  if (totalSteps === 0) return null;

  const showDots = totalSteps <= DOT_THRESHOLD;
  const milestones = showDots ? [] : computeMilestones(totalSteps);

  return (
    <div className="absolute bottom-3 left-6 right-6 flex items-center gap-2 pointer-events-none overflow-hidden">
      <div
        ref={trackRef}
        className="relative h-4 flex-1 flex items-center cursor-pointer pointer-events-auto"
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
      >
        {/* Track background */}
        <div className="absolute h-[2px] w-full rounded-full bg-bg-tertiary" />
        {/* Fill */}
        <div ref={fillRef} className="absolute h-[2px] rounded-full bg-signal" />

        {/* Step dots: all dots ≤ threshold, milestones only above */}
        {(showDots ? Array.from({ length: totalSteps }, (_, i) => i) : milestones).map((i) => {
          const x = totalSteps > 1 ? (i / (totalSteps - 1)) * 100 : 50;
          return (
            <button
              key={i}
              onClick={(e) => {
                e.stopPropagation();
                handleDotClick(i);
              }}
              className={`absolute -translate-x-1/2 rounded-full bg-bg-tertiary hover:bg-signal transition-colors ${
                showDots ? "h-[6px] w-[6px]" : "h-[5px] w-[5px]"
              }`}
              style={{ left: `${x}%` }}
            />
          );
        })}

        {/* Draggable handle */}
        <div
          ref={handleRef}
          className="absolute h-2 w-2 -translate-x-1/2 rounded-full bg-signal shadow-sm"
        />
      </div>

      {/* Step counter — ref-updated at 60fps */}
      <span
        ref={counterRef}
        className="text-[11px] font-mono text-text-tertiary tabular-nums select-none pointer-events-auto"
      >
        1/{totalSteps}
      </span>
    </div>
  );
}
