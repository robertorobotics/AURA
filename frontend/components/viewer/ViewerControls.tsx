"use client";

interface ViewerControlsProps {
  exploded: boolean;
  onToggleExplode: () => void;
  wireframe: boolean;
  onToggleWireframe: () => void;
  animating: boolean;
  paused: boolean;
  onToggleAnimation: () => void;
  onStepForward: () => void;
  onStepBackward: () => void;
  onResetView: () => void;
  onFitToView: () => void;
  onReplayDemo: () => void;
  demoPlayed: boolean;
}

function IconButton({
  title,
  active,
  onClick,
  children,
}: {
  title: string;
  active?: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      title={title}
      onClick={onClick}
      className={`pointer-events-auto flex h-7 w-7 items-center justify-center rounded-md bg-white/85 backdrop-blur-sm transition-colors hover:bg-white ${
        active ? "text-signal" : "text-text-secondary"
      }`}
    >
      {children}
    </button>
  );
}

export function ViewerControls({
  exploded,
  onToggleExplode,
  wireframe,
  onToggleWireframe,
  animating,
  paused,
  onToggleAnimation,
  onStepForward,
  onStepBackward,
  onResetView,
  onFitToView,
  onReplayDemo,
  demoPlayed,
}: ViewerControlsProps) {
  const showPause = animating && !paused;

  return (
    <div className="pointer-events-none absolute right-3 top-3 flex flex-col gap-1 rounded-md bg-white/70 p-1 backdrop-blur-sm">
      <IconButton title="Reset view (R)" onClick={onResetView}>
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
          <path d="M2 8a6 6 0 0 1 10.5-4M14 8a6 6 0 0 1-10.5 4" />
          <path d="M12.5 2v2.5H10M3.5 14v-2.5H6" />
        </svg>
      </IconButton>

      <IconButton title="Fit to view" onClick={onFitToView}>
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
          <rect x="4" y="4" width="8" height="8" rx="0.5" />
          <path d="M2 5V2h3M14 5V2h-3M2 11v3h3M14 11v3h-3" />
        </svg>
      </IconButton>

      <IconButton title="Toggle wireframe" active={wireframe} onClick={onToggleWireframe}>
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
          <rect x="3" y="3" width="10" height="10" />
          <line x1="8" y1="3" x2="8" y2="13" />
          <line x1="3" y1="8" x2="13" y2="8" />
        </svg>
      </IconButton>

      <IconButton title="Toggle explode" active={exploded} onClick={onToggleExplode}>
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
          <path d="M8 2V5M8 11V14M2 8H5M11 8H14" />
          <circle cx="8" cy="8" r="2" />
        </svg>
      </IconButton>

      <div className="my-1 h-px bg-bg-tertiary" />

      {demoPlayed && (
        <IconButton title="Replay demo" onClick={onReplayDemo}>
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
            <path d="M2.5 8a5.5 5.5 0 0 1 9.5-3.75" />
            <path d="M13.5 8a5.5 5.5 0 0 1-9.5 3.75" />
            <path d="M12 2v2.5h-2.5" />
            <path d="M5 8l-2 2 2 2" />
          </svg>
        </IconButton>
      )}

      <IconButton title="Step backward" onClick={onStepBackward}>
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
          <path d="M10 12L6 8L10 4" />
        </svg>
      </IconButton>

      <IconButton title={showPause ? "Pause" : "Play"} active={animating} onClick={onToggleAnimation}>
        {showPause ? (
          <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
            <rect x="4" y="3" width="3" height="10" rx="0.5" />
            <rect x="9" y="3" width="3" height="10" rx="0.5" />
          </svg>
        ) : (
          <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
            <path d="M5 3L12 8L5 13V3Z" />
          </svg>
        )}
      </IconButton>

      <IconButton title="Step forward" onClick={onStepForward}>
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
          <path d="M6 4L10 8L6 12" />
        </svg>
      </IconButton>
    </div>
  );
}
