"use client";

import { useCallback, useEffect, useRef, useState } from "react";

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
  const [dragging, setDragging] = useState(false);

  // 60fps handle position sync via rAF (reads from ref, no React re-renders)
  useEffect(() => {
    let raf: number;
    function tick() {
      const progress = scrubberProgressRef.current ?? 0;
      const pct = `${progress * 100}%`;
      if (handleRef.current) handleRef.current.style.left = pct;
      if (fillRef.current) fillRef.current.style.width = pct;
      raf = requestAnimationFrame(tick);
    }
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [scrubberProgressRef]);

  const computeT = useCallback(
    (clientX: number) => {
      if (!trackRef.current) return 0;
      const rect = trackRef.current.getBoundingClientRect();
      return Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    },
    [],
  );

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

  // Step dot click
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

  return (
    <div className="absolute bottom-3 left-6 right-6 flex items-center gap-2">
      <div
        ref={trackRef}
        className="relative h-4 flex-1 flex items-center cursor-pointer"
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
      >
        {/* Track background */}
        <div className="absolute h-[2px] w-full rounded-full bg-bg-tertiary" />
        {/* Fill */}
        <div ref={fillRef} className="absolute h-[2px] rounded-full bg-accent" />

        {/* Step dots */}
        {Array.from({ length: totalSteps }, (_, i) => {
          const x = totalSteps > 1 ? (i / (totalSteps - 1)) * 100 : 50;
          return (
            <button
              key={i}
              onClick={(e) => {
                e.stopPropagation();
                handleDotClick(i);
              }}
              className="absolute h-[6px] w-[6px] -translate-x-1/2 rounded-full bg-bg-tertiary hover:bg-accent transition-colors"
              style={{ left: `${x}%` }}
            />
          );
        })}

        {/* Draggable handle */}
        <div
          ref={handleRef}
          className="absolute h-2 w-2 -translate-x-1/2 rounded-full bg-accent shadow-sm"
        />
      </div>

      <span className="text-[11px] font-mono text-text-tertiary tabular-nums select-none">
        {Math.round((scrubberProgressRef.current ?? 0) * totalSteps) + 1}/{totalSteps}
      </span>
    </div>
  );
}
