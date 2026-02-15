// Pure execution-animation logic — no React, no Three.js.
// Computes per-part render state from ExecutionState during live assembly.

import type { Part, AssemblyStep, StepStatus, ExecutionState } from "./types";
import {
  type Vec3,
  type PartRenderState,
  computeApproachPosition,
  easeInOut,
  partStepIndex,
} from "./animation";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Per-step animation tracking (updated each frame). */
export interface StepAnimState {
  stepId: string;
  status: StepStatus;
  /** Seconds since this step entered its current status. */
  statusTime: number;
  /** 0..1 progress of approach-to-final motion (only meaningful when running). */
  motionProgress: number;
}

export type EndEffectorPhase = "idle" | "approach" | "grasp" | "place" | "retract";

/** Aggregate execution animation state (stored in a ref, mutated per-frame). */
export interface ExecutionAnimState {
  stepAnims: Record<string, StepAnimState>;
  prevRunningStepId: string | null;
  // TODO: Remove endEffectorTarget once camera tracking is refactored
  endEffectorTarget: Vec3;
  // TODO: Remove endEffectorPhase once camera tracking is refactored
  endEffectorPhase: EndEffectorPhase;
  /** 200ms countdown between steps. */
  transitionPauseRemaining: number;
}

export const INITIAL_EXEC_ANIM: ExecutionAnimState = {
  stepAnims: {},
  prevRunningStepId: null,
  endEffectorTarget: [0, 0, 0],
  endEffectorPhase: "idle",
  transitionPauseRemaining: 0,
};

// ---------------------------------------------------------------------------
// Timing constants
// ---------------------------------------------------------------------------

export const EXEC_TIMING = {
  STEP_MOTION_DURATION: 1.5,
  STEP_TRANSITION_PAUSE: 0.3,
  SUCCESS_FLASH_DURATION: 0.3,
  SUCCESS_SETTLE_DURATION: 0.2, // ease final motion on success
  FAILURE_FLASH_DURATION: 0.5,
  HUMAN_PULSE_SPEED: 2.0,
  PRESS_FIT_BOUNCE_AMPLITUDE: 0.3, // fraction of offset distance
  PRESS_FIT_BOUNCE_DURATION: 0.3,
} as const;

// ---------------------------------------------------------------------------
// Primitive-specific approach offsets
// ---------------------------------------------------------------------------

function vec3(v: number[] | undefined | null): Vec3 {
  return [v?.[0] ?? 0, v?.[1] ?? 0, v?.[2] ?? 0];
}

/** Compute the start position for a part based on its step's primitive type. */
export function primitiveApproachOffset(
  part: Part,
  step: AssemblyStep | undefined,
  assemblyRadius: number,
): Vec3 {
  const base: Vec3 = vec3(part.position);
  const dims = vec3(part.dimensions ?? [0.05, 0.05, 0.05]);
  const maxDim = Math.max(dims[0], dims[1], dims[2]);
  const offset = Math.max(maxDim * 2, assemblyRadius * 0.15);

  const pType = step?.primitiveType ?? "";

  switch (pType) {
    case "pick": {
      // Start from layout position (tray) if available
      const layout: Vec3 = part.layoutPosition
        ? [part.layoutPosition[0], part.layoutPosition[1], part.layoutPosition[2]]
        : [base[0] - offset * 0.3, base[1] - offset, base[2]];
      return layout;
    }

    case "place":
      // Descend from directly above
      return [base[0], base[1] + offset, base[2]];

    case "insert":
    case "linear_insert": {
      // Slide along approach vector
      const a = vec3(part.graspPoints[0]?.approach);
      const ax = a[0] || 0, ay = a[1] || -1, az = a[2] || 0;
      return [base[0] - ax * offset, base[1] - ay * offset, base[2] - az * offset];
    }

    case "press_fit": {
      // Push down from above
      const dir = vec3(
        step?.primitiveParams?.direction as number[] | undefined,
      );
      const dx = dir[0] || 0, dy = dir[1] || -1, dz = dir[2] || 0;
      return [base[0] - dx * offset, base[1] - dy * offset, base[2] - dz * offset];
    }

    default:
      return computeApproachPosition(part, assemblyRadius);
  }
}

// ---------------------------------------------------------------------------
// Per-frame state machine tick
// ---------------------------------------------------------------------------

/** Advance execution animation state by one frame. */
export function tickExecutionAnim(
  prev: ExecutionAnimState,
  delta: number,
  executionState: ExecutionState,
  stepOrder: string[],
): ExecutionAnimState {
  // Freeze animation when paused
  if (executionState.phase === "paused") return prev;

  const next: ExecutionAnimState = {
    stepAnims: { ...prev.stepAnims },
    prevRunningStepId: prev.prevRunningStepId,
    endEffectorTarget: [...prev.endEffectorTarget] as Vec3,
    endEffectorPhase: prev.endEffectorPhase,
    transitionPauseRemaining: Math.max(0, prev.transitionPauseRemaining - delta),
  };

  // Sync step animation states with execution step states
  for (const stepId of stepOrder) {
    const runtimeState = executionState.stepStates[stepId];
    if (!runtimeState) continue;

    const prevAnim = prev.stepAnims[stepId];
    const statusChanged = prevAnim?.status !== runtimeState.status;

    if (!prevAnim || statusChanged) {
      // Preserve motionProgress on success so we can ease the final distance
      const preserveOnSuccess =
        statusChanged && runtimeState.status === "success";
      next.stepAnims[stepId] = {
        stepId,
        status: runtimeState.status,
        statusTime: 0,
        motionProgress: preserveOnSuccess
          ? (prevAnim?.motionProgress ?? 1)
          : 0,
      };
    } else {
      // Advance timers
      const updated = { ...prevAnim, statusTime: prevAnim.statusTime + delta };
      if (runtimeState.status === "running") {
        updated.motionProgress = Math.min(
          1,
          updated.motionProgress + delta / EXEC_TIMING.STEP_MOTION_DURATION,
        );
      }
      next.stepAnims[stepId] = updated;
    }
  }

  // Detect step transitions for inter-step pause
  const currentRunning = executionState.currentStepId;
  if (currentRunning !== prev.prevRunningStepId) {
    if (prev.prevRunningStepId != null && currentRunning != null) {
      next.transitionPauseRemaining = EXEC_TIMING.STEP_TRANSITION_PAUSE;
    }
    next.prevRunningStepId = currentRunning;
  }

  // TODO: endEffectorPhase is no longer consumed after RobotArm removal.
  // Kept in the type for future real-arm visualization.
  next.endEffectorPhase = "idle";

  return next;
}

// ---------------------------------------------------------------------------
// Per-part render state computation
// ---------------------------------------------------------------------------

/** Compute a single part's render state during execution. */
export function computeExecutionPartState(
  part: Part,
  step: AssemblyStep | undefined,
  stepAnim: StepAnimState | undefined,
  assemblyRadius: number,
  clock: number,
  isNextStep: boolean,
): PartRenderState {
  const base: Vec3 = vec3(part.position);
  const approach = primitiveApproachOffset(part, step, assemblyRadius);
  const status = stepAnim?.status ?? "pending";

  switch (status) {
    case "pending": {
      const layoutPos: Vec3 = part.layoutPosition
        ? [part.layoutPosition[0], part.layoutPosition[1], part.layoutPosition[2]]
        : base;
      if (isNextStep) {
        // Pulsing preview at layout position (on the tray)
        const previewPos: Vec3 = part.layoutPosition
          ? [part.layoutPosition[0], part.layoutPosition[1], part.layoutPosition[2]]
          : approach;
        return {
          position: previewPos,
          opacity: 0.4 + 0.1 * Math.sin(clock * 3),
          visualState: "active",
        };
      }
      // Future parts: at layout position (on the tray)
      return { position: layoutPos, opacity: 0.85, visualState: "complete" };
    }

    case "running":
    case "retrying": {
      const t = easeInOut(stepAnim?.motionProgress ?? 0);
      const pos: Vec3 = [
        approach[0] + (base[0] - approach[0]) * t,
        approach[1] + (base[1] - approach[1]) * t,
        approach[2] + (base[2] - approach[2]) * t,
      ];
      return {
        position: pos,
        opacity: 0.3 + 0.7 * t,
        visualState: "active",
        colorOverride: status === "retrying" ? "#D4930A" : null,
        emissiveIntensity: 0,
      };
    }

    case "success": {
      const flashT = stepAnim?.statusTime ?? 1;
      const flashing = flashT < EXEC_TIMING.SUCCESS_FLASH_DURATION;

      // Ease the final motion to assembled position (no snap)
      const mp = stepAnim?.motionProgress ?? 1;
      let settledMp = 1;
      if (mp < 1 && flashT < EXEC_TIMING.SUCCESS_SETTLE_DURATION) {
        settledMp = mp + (1 - mp) * easeInOut(flashT / EXEC_TIMING.SUCCESS_SETTLE_DURATION);
      }
      const st = easeInOut(settledMp);
      let pos: Vec3 = [
        approach[0] + (base[0] - approach[0]) * st,
        approach[1] + (base[1] - approach[1]) * st,
        approach[2] + (base[2] - approach[2]) * st,
      ];

      // Press-fit bounce effect (only after settling)
      if (
        settledMp >= 1 &&
        step?.primitiveType === "press_fit" &&
        flashT < EXEC_TIMING.PRESS_FIT_BOUNCE_DURATION
      ) {
        const bounceT = flashT / EXEC_TIMING.PRESS_FIT_BOUNCE_DURATION;
        const bounce = Math.sin(bounceT * Math.PI) * EXEC_TIMING.PRESS_FIT_BOUNCE_AMPLITUDE;
        const dir = vec3(step.primitiveParams?.direction as number[] | undefined);
        const dx = dir[0] || 0, dy = dir[1] || -1, dz = dir[2] || 0;
        const offsetDist = Math.max(
          Math.max(...(part.dimensions ?? [0.05])) * 3,
          assemblyRadius * 0.5,
        ) * bounce;
        pos = [base[0] - dx * offsetDist, base[1] - dy * offsetDist, base[2] - dz * offsetDist];
      }

      return {
        position: pos,
        opacity: 1,
        visualState: "complete",
        colorOverride: flashing ? "#2A9D5C" : null,
        emissiveIntensity: flashing ? 0.4 * (1 - flashT / EXEC_TIMING.SUCCESS_FLASH_DURATION) : 0,
      };
    }

    case "failed": {
      const flashT = stepAnim?.statusTime ?? 1;
      const flashing = flashT < EXEC_TIMING.FAILURE_FLASH_DURATION;
      // Hold at current interpolated position
      const mp = stepAnim?.motionProgress ?? 0;
      const t = easeInOut(mp);
      const pos: Vec3 = [
        approach[0] + (base[0] - approach[0]) * t,
        approach[1] + (base[1] - approach[1]) * t,
        approach[2] + (base[2] - approach[2]) * t,
      ];
      return {
        position: pos,
        opacity: 1,
        visualState: "active",
        colorOverride: flashing ? "#D43825" : null,
        emissiveIntensity: flashing ? 0.5 * (1 - flashT / EXEC_TIMING.FAILURE_FLASH_DURATION) : 0,
      };
    }

    case "human": {
      const pulse = 0.85 + 0.15 * Math.sin(clock * EXEC_TIMING.HUMAN_PULSE_SPEED * Math.PI * 2);
      const mp = stepAnim?.motionProgress ?? 0;
      const t = easeInOut(mp);
      const pos: Vec3 = [
        approach[0] + (base[0] - approach[0]) * t,
        approach[1] + (base[1] - approach[1]) * t,
        approach[2] + (base[2] - approach[2]) * t,
      ];
      return {
        position: pos,
        opacity: pulse,
        visualState: "active",
        colorOverride: "#D4930A",
        emissiveIntensity: 0.2 + 0.2 * Math.sin(clock * EXEC_TIMING.HUMAN_PULSE_SPEED * Math.PI * 2),
      };
    }

    default:
      return { position: base, opacity: 1, visualState: "complete" };
  }
}

// ---------------------------------------------------------------------------
// End-effector target computation
// ---------------------------------------------------------------------------

/**
 * Compute end-effector target position for the robot arm.
 * TODO: No longer called after RobotArm removal. Keep for future real-arm visualization.
 */
export function computeEndEffectorTarget(
  part: Part,
  step: AssemblyStep | undefined,
  stepAnim: StepAnimState | undefined,
  assemblyRadius: number,
  neutralPos: Vec3,
): Vec3 {
  if (!stepAnim || stepAnim.status === "pending" || stepAnim.status === "success") {
    return neutralPos;
  }

  const base: Vec3 = vec3(part.position);
  const approach = primitiveApproachOffset(part, step, assemblyRadius);
  const mp = stepAnim.motionProgress;

  if (mp < 0.3) {
    // Moving to approach position
    return approach;
  }
  if (mp < 0.7) {
    // Interpolating approach → base
    const t = (mp - 0.3) / 0.4;
    return [
      approach[0] + (base[0] - approach[0]) * t,
      approach[1] + (base[1] - approach[1]) * t,
      approach[2] + (base[2] - approach[2]) * t,
    ];
  }
  // At final position
  return base;
}
