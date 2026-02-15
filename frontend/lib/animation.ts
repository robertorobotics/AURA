// Pure animation logic — no React, no Three.js. Drives the 3D viewer state machine.

import type { Part } from "./types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type AnimationPhase =
  | "idle"
  | "demo_fadein"
  | "demo_hold"
  | "demo_explode"
  | "demo_assemble"
  | "playing"
  | "scrubbing";

export interface AnimationState {
  phase: AnimationPhase;
  /** Seconds elapsed within the current phase. */
  phaseTime: number;
  /** Index into stepOrder for playing / demo_assemble. */
  stepIndex: number;
  /** 0..1 interpolation within the current step (ease-in portion only). */
  stepProgress: number;
  paused: boolean;
  demoPlayed: boolean;
}

export type Vec3 = [number, number, number];

export interface PartRenderState {
  position: Vec3;
  /** Euler XYZ rotation. Undefined = use part.rotation (assembled). */
  rotation?: Vec3;
  opacity: number;
  visualState: "ghost" | "active" | "complete";
  /** Execution mode: override part color (e.g. red flash on fail). */
  colorOverride?: string | null;
  /** Execution mode: emissive glow intensity 0..1. */
  emissiveIntensity?: number;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const TIMING = {
  DEMO_FADEIN_PER_PART: 0.1,
  DEMO_HOLD: 0.5,
  DEMO_EXPLODE: 0.6,
  STEP_EASE_IN: 0.8,
  STEP_HOLD: 0.2,
} as const;

const STEP_DURATION = TIMING.STEP_EASE_IN + TIMING.STEP_HOLD;

// ---------------------------------------------------------------------------
// Easing
// ---------------------------------------------------------------------------

/** Cubic ease-in-out: smooth acceleration/deceleration. */
export function easeInOut(t: number): number {
  const c = Math.max(0, Math.min(1, t));
  return c < 0.5 ? 4 * c * c * c : 1 - Math.pow(-2 * c + 2, 3) / 2;
}

// ---------------------------------------------------------------------------
// Geometry helpers
// ---------------------------------------------------------------------------

/** Safe Vec3 from an optional number[]. */
function vec3(v: number[] | undefined | null): Vec3 {
  return [v?.[0] ?? 0, v?.[1] ?? 0, v?.[2] ?? 0];
}

export function computeCentroid(parts: Part[]): Vec3 {
  if (parts.length === 0) return [0, 0, 0];
  let sx = 0, sy = 0, sz = 0;
  for (const p of parts) {
    const v = vec3(p.position);
    sx += v[0]; sy += v[1]; sz += v[2];
  }
  const n = parts.length;
  return [sx / n, sy / n, sz / n];
}

/** Max distance from centroid to any part — used to scale offsets. */
export function computeAssemblyRadius(parts: Part[], centroid: Vec3): number {
  let maxR = 0;
  for (const p of parts) {
    const v = vec3(p.position);
    const dx = v[0] - centroid[0];
    const dy = v[1] - centroid[1];
    const dz = v[2] - centroid[2];
    maxR = Math.max(maxR, Math.sqrt(dx * dx + dy * dy + dz * dz));
  }
  return maxR || 0.1;
}

export function computeExplodeOffset(
  part: Part,
  centroid: Vec3,
  assemblyRadius: number,
): Vec3 {
  const pos = vec3(part.position);
  const dims = vec3(part.dimensions ?? [0.05, 0.05, 0.05]);
  const maxDim = Math.max(dims[0], dims[1], dims[2]);
  const dist = Math.max(maxDim * 2.5, assemblyRadius * 0.4);

  const dx = pos[0] - centroid[0];
  const dy = pos[1] - centroid[1];
  const dz = pos[2] - centroid[2];
  const len = Math.sqrt(dx * dx + dy * dy + dz * dz);

  if (len < 0.0001) {
    const a = vec3(part.graspPoints[0]?.approach);
    const ax = a[0] || 0, ay = a[1] || -1, az = a[2] || 0;
    return [-ax * dist, -ay * dist, -az * dist];
  }
  return [(dx / len) * dist, (dy / len) * dist, (dz / len) * dist];
}

/** Max distance from centroid to any part's position OR layoutPosition — full workspace extent. */
export function computeWorkspaceRadius(parts: Part[], centroid: Vec3): number {
  let maxR = 0;
  for (const p of parts) {
    const v = vec3(p.position);
    const dx = v[0] - centroid[0], dy = v[1] - centroid[1], dz = v[2] - centroid[2];
    maxR = Math.max(maxR, Math.sqrt(dx * dx + dy * dy + dz * dz));
    if (p.layoutPosition) {
      const lx = p.layoutPosition[0] - centroid[0];
      const ly = p.layoutPosition[1] - centroid[1];
      const lz = p.layoutPosition[2] - centroid[2];
      maxR = Math.max(maxR, Math.sqrt(lx * lx + ly * ly + lz * lz));
    }
  }
  return maxR || 0.1;
}

/** Approach position: offset along inverted approach vector (just before insertion). */
export function computeApproachPosition(part: Part, assemblyRadius: number): Vec3 {
  const base = vec3(part.position);
  const a = vec3(part.graspPoints[0]?.approach);
  const ax = a[0] || 0, ay = a[1] || -1, az = a[2] || 0;
  const dims = vec3(part.dimensions ?? [0.05, 0.05, 0.05]);
  const d = Math.max(Math.max(dims[0], dims[1], dims[2]) * 3, assemblyRadius * 0.5);
  return [base[0] - ax * d, base[1] - ay * d, base[2] - az * d];
}

/** Linear interpolation between two Vec3 values. */
export function lerpVec3(a: Vec3, b: Vec3, t: number): Vec3 {
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
}

/**
 * 3-phase animation for a part being assembled in the current step.
 *
 *   Phase 1 (0.00–0.25): Lift from layoutPosition straight up by liftHeight.
 *   Phase 2 (0.25–0.65): Transit from lifted position to approach position.
 *   Phase 3 (0.65–1.00): Insert from approach position to assembled position.
 */
export function computePhasePosition(
  part: Part,
  stepProgress: number,
  assemblyRadius: number,
): { position: Vec3; rotation: Vec3; opacity: number } {
  const layout: Vec3 = (part.layoutPosition as Vec3) ?? (part.position as Vec3) ?? [0, 0, 0];
  const assembled: Vec3 = (part.position as Vec3) ?? [0, 0, 0];
  const layoutRot: Vec3 = (part.layoutRotation as Vec3) ?? [0, 0, 0];
  const assembledRot: Vec3 = (part.rotation as Vec3) ?? [0, 0, 0];
  const approach = computeApproachPosition(part, assemblyRadius);
  const maxDim = Math.max(...(part.dimensions ?? [0.05, 0.05, 0.05]));
  const liftHeight = Math.max(maxDim * 2, 0.04);
  const lifted: Vec3 = [layout[0], layout[1] + liftHeight, layout[2]];

  if (stepProgress < 0.25) {
    // Phase 1: Lift from tray — keep layout rotation
    const t = easeInOut(stepProgress / 0.25);
    return { position: lerpVec3(layout, lifted, t), rotation: layoutRot, opacity: 0.4 + 0.6 * t };
  }
  if (stepProgress < 0.65) {
    // Phase 2: Transit to approach — keep layout rotation
    const t = easeInOut((stepProgress - 0.25) / 0.4);
    return { position: lerpVec3(lifted, approach, t), rotation: layoutRot, opacity: 1 };
  }
  // Phase 3: Insert — lerp rotation from layout to assembled
  const t = easeInOut((stepProgress - 0.65) / 0.35);
  return { position: lerpVec3(approach, assembled, t), rotation: lerpVec3(layoutRot, assembledRot, t), opacity: 1 };
}

// ---------------------------------------------------------------------------
// Phase machine
// ---------------------------------------------------------------------------

export const INITIAL_STATE: AnimationState = {
  phase: "idle",
  phaseTime: 0,
  stepIndex: 0,
  stepProgress: 0,
  paused: false,
  demoPlayed: false,
};

export function tickPhase(
  state: AnimationState,
  delta: number,
  partCount: number,
  stepCount: number,
): AnimationState {
  if (state.paused || state.phase === "idle" || state.phase === "scrubbing") return state;

  const t = state.phaseTime + delta;

  switch (state.phase) {
    case "demo_fadein": {
      const dur = partCount * TIMING.DEMO_FADEIN_PER_PART;
      if (t >= dur) return { ...state, phase: "demo_hold", phaseTime: 0 };
      return { ...state, phaseTime: t };
    }
    case "demo_hold": {
      if (t >= TIMING.DEMO_HOLD) return { ...state, phase: "demo_explode", phaseTime: 0 };
      return { ...state, phaseTime: t };
    }
    case "demo_explode": {
      if (t >= TIMING.DEMO_EXPLODE) {
        return { ...state, phase: "demo_assemble", phaseTime: 0, stepIndex: 0, stepProgress: 0 };
      }
      return { ...state, phaseTime: t };
    }
    case "demo_assemble":
    case "playing": {
      // Advance within steps
      const stepLocalTime = t - state.stepIndex * STEP_DURATION;
      if (stepLocalTime >= STEP_DURATION) {
        const nextIdx = state.stepIndex + 1;
        if (nextIdx >= stepCount) {
          return {
            ...state,
            phase: "idle",
            phaseTime: 0,
            stepIndex: stepCount - 1,
            stepProgress: 1,
            demoPlayed: true,
          };
        }
        return { ...state, phaseTime: t, stepIndex: nextIdx, stepProgress: 0 };
      }
      const progress = Math.min(1, stepLocalTime / TIMING.STEP_EASE_IN);
      return { ...state, phaseTime: t, stepProgress: progress };
    }
    default:
      return state;
  }
}

// ---------------------------------------------------------------------------
// Per-part rendering
// ---------------------------------------------------------------------------

/** Find the first stepOrder index whose step references this part. */
export function partStepIndex(
  partId: string,
  stepOrder: string[],
  steps: Record<string, { partIds: string[] }>,
): number {
  for (let i = 0; i < stepOrder.length; i++) {
    const sid = stepOrder[i];
    if (sid && steps[sid]?.partIds.includes(partId)) return i;
  }
  return -1;
}

export function computePartAnimation(
  part: Part,
  state: AnimationState,
  stepOrder: string[],
  steps: Record<string, { partIds: string[] }>,
  assemblyRadius: number,
): PartRenderState {
  const base: Vec3 = (part.position as Vec3 | undefined) ?? [0, 0, 0];
  const assembledRot: Vec3 = (part.rotation as Vec3) ?? [0, 0, 0];
  const layoutRot: Vec3 = (part.layoutRotation as Vec3) ?? [0, 0, 0];

  // Idle — base parts and post-demo at assembled position; pre-demo at layout position
  if (state.phase === "idle") {
    if (part.isBase) {
      return { position: base, rotation: assembledRot, opacity: 1, visualState: "complete" };
    }
    if (!state.demoPlayed) {
      const layout: Vec3 = part.layoutPosition ?? base;
      return { position: layout, rotation: layoutRot, opacity: 0.9, visualState: "ghost" };
    }
    return { position: base, rotation: assembledRot, opacity: 1, visualState: "complete" };
  }

  // Fade-in — sequential opacity (assembled rotation)
  if (state.phase === "demo_fadein") {
    const idx = partStepIndex(part.id, stepOrder, steps);
    const partIdx = idx >= 0 ? idx : 0;
    const fadeStart = partIdx * TIMING.DEMO_FADEIN_PER_PART;
    const fadeEnd = fadeStart + TIMING.DEMO_FADEIN_PER_PART;
    const opacity = Math.min(1, Math.max(0, (state.phaseTime - fadeStart) / (fadeEnd - fadeStart)));
    return { position: base, rotation: assembledRot, opacity, visualState: "complete" };
  }

  // Hold — all visible (assembled rotation)
  if (state.phase === "demo_hold") {
    return { position: base, rotation: assembledRot, opacity: 1, visualState: "complete" };
  }

  // Explode — handled externally via explodeFactor, position stays at base
  if (state.phase === "demo_explode") {
    return { position: base, rotation: assembledRot, opacity: 1, visualState: "complete" };
  }

  // Playing or demo_assemble — step-based interpolation

  // Base part: always at assembled position, never animated
  if (part.isBase) {
    return { position: base, rotation: assembledRot, opacity: 1, visualState: "complete" };
  }

  const psi = partStepIndex(part.id, stepOrder, steps);
  if (psi < 0) return { position: base, rotation: assembledRot, opacity: 1, visualState: "complete" };

  if (psi < state.stepIndex) {
    return { position: base, rotation: assembledRot, opacity: 1, visualState: "complete" };
  }
  if (psi === state.stepIndex) {
    const { position, rotation, opacity } = computePhasePosition(part, state.stepProgress, assemblyRadius);
    return { position, rotation, opacity, visualState: "active" };
  }
  // Future step — at layout position, ghost
  const layout: Vec3 = part.layoutPosition ?? computeApproachPosition(part, assemblyRadius);
  return { position: layout, rotation: layoutRot, opacity: 0.9, visualState: "ghost" };
}

// ---------------------------------------------------------------------------
// Scrubber helpers
// ---------------------------------------------------------------------------

export function scrubberToStep(
  t: number,
  stepCount: number,
): { stepIndex: number; stepProgress: number } {
  if (stepCount <= 0) return { stepIndex: 0, stepProgress: 0 };
  const clamped = Math.max(0, Math.min(1, t));
  const raw = clamped * stepCount;
  const idx = Math.min(Math.floor(raw), stepCount - 1);
  const frac = raw - idx;
  const progress = Math.min(1, frac / (TIMING.STEP_EASE_IN / STEP_DURATION));
  return { stepIndex: idx, stepProgress: progress };
}

export function stepToScrubber(
  stepIndex: number,
  stepProgress: number,
  stepCount: number,
): number {
  if (stepCount <= 0) return 0;
  const easeFrac = (stepProgress * TIMING.STEP_EASE_IN) / STEP_DURATION;
  return (stepIndex + easeFrac) / stepCount;
}
