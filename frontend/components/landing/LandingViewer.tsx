"use client";

// ---------------------------------------------------------------------------
// Lightweight 3D viewer for the landing page. Autoplay + auto-loop, no
// controls overlay. Reuses existing viewer components (AnimationController,
// PartMesh, GroundPlane) which are all prop-driven with no context coupling.
// ---------------------------------------------------------------------------

import { useCallback, useEffect, useMemo, useRef } from "react";
import { Canvas } from "@react-three/fiber";
import { OrbitControls, Environment } from "@react-three/drei";
import type { Assembly, ExecutionState } from "@/lib/types";
import type { AnimationPhase } from "@/lib/animation";
import { partStepIndex } from "@/lib/animation";
import { useAnimationControls } from "@/lib/useAnimationControls";
import { INITIAL_EXEC_ANIM } from "@/lib/executionAnimation";
import type { ExecutionAnimState } from "@/lib/executionAnimation";
import { GroundPlane } from "@/components/viewer/GroundPlane";
import { PartMesh } from "@/components/viewer/PartMesh";
import { AnimationController } from "@/components/viewer/AnimationController";

// ---------------------------------------------------------------------------
// Scene layout — duplicated from AssemblyViewer. Extract to shared module
// if a third consumer appears.
// ---------------------------------------------------------------------------

interface SceneLayout {
  cameraPos: [number, number, number];
  target: [number, number, number];
  near: number;
  far: number;
  maxDist: number;
  groundY: number;
  gridCell: number;
  gridSection: number;
}

const DEFAULTS: SceneLayout = {
  cameraPos: [0.15, 0.12, 0.15],
  target: [0, 0.02, 0],
  near: 0.001,
  far: 10,
  maxDist: 1,
  groundY: -0.02,
  gridCell: 0.02,
  gridSection: 0.1,
};

function computeLayout(parts: { position?: number[]; dimensions?: number[] }[]): SceneLayout {
  if (parts.length === 0) return DEFAULTS;

  let minX = Infinity, minY = Infinity, minZ = Infinity;
  let maxX = -Infinity, maxY = -Infinity, maxZ = -Infinity;

  for (const part of parts) {
    const px = part.position?.[0] ?? 0;
    const py = part.position?.[1] ?? 0;
    const pz = part.position?.[2] ?? 0;
    const dx = part.dimensions?.[0] ?? 0.05;
    const dy = part.dimensions?.[1] ?? 0.05;
    const dz = part.dimensions?.[2] ?? 0.05;
    minX = Math.min(minX, px - dx / 2);
    minY = Math.min(minY, py - dy / 2);
    minZ = Math.min(minZ, pz - dz / 2);
    maxX = Math.max(maxX, px + dx / 2);
    maxY = Math.max(maxY, py + dy / 2);
    maxZ = Math.max(maxZ, pz + dz / 2);
  }

  const cx = (minX + maxX) / 2;
  const cy = (minY + maxY) / 2;
  const cz = (minZ + maxZ) / 2;
  const extentX = maxX - minX;
  const extentY = maxY - minY;
  const extentZ = maxZ - minZ;
  const radius = Math.max(extentX, extentY, extentZ) * 0.75;

  if (radius < 0.001) return DEFAULTS;

  return {
    cameraPos: [cx + radius, cy + radius * 0.8, cz + radius],
    target: [cx, cy, cz],
    near: radius * 0.001,
    far: radius * 40,
    maxDist: radius * 10,
    groundY: minY - radius * 0.02,
    gridCell: radius * 0.04,
    gridSection: radius * 0.2,
  };
}

// ---------------------------------------------------------------------------
// LandingViewer
// ---------------------------------------------------------------------------

interface LandingViewerProps {
  assembly: Assembly;
}

export function LandingViewer({ assembly }: LandingViewerProps) {
  const parts = useMemo(() => Object.values(assembly.parts), [assembly]);
  const stepOrder = assembly.stepOrder;
  const steps = assembly.steps;
  const totalSteps = stepOrder.length;

  const anim = useAnimationControls(assembly.id, totalSteps);
  const layout = useMemo(() => computeLayout(parts), [parts]);

  // Execution props (always inactive on landing page)
  const executionAnimRef = useRef<ExecutionAnimState>({ ...INITIAL_EXEC_ANIM });
  const idleExecState = useMemo<ExecutionState>(() => ({
    phase: "idle", assemblyId: null, currentStepId: null,
    stepStates: {}, runNumber: 0, startTime: null, elapsedMs: 0, overallSuccessRate: 0,
  }), []);

  // Pre-compute part → first step id (needed by PartMesh for visual state)
  const partToStepId = useMemo(() => {
    const map: Record<string, string | null> = {};
    for (const part of parts) {
      const idx = partStepIndex(part.id, assembly.stepOrder, assembly.steps);
      map[part.id] = idx >= 0 ? (assembly.stepOrder[idx] ?? null) : null;
    }
    return map;
  }, [assembly, parts]);

  // Auto-loop: restart demo 2s after it finishes
  const loopTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const hasPlayedOnce = useRef(false);

  const onPhaseChange = useCallback(
    (phase: AnimationPhase) => {
      anim.onPhaseChange(phase);
      if (phase === "demo_fadein") hasPlayedOnce.current = true;
      if (phase === "idle" && hasPlayedOnce.current) {
        if (loopTimerRef.current) clearTimeout(loopTimerRef.current);
        loopTimerRef.current = setTimeout(() => anim.replayDemo(), 2000);
      }
    },
    [anim],
  );

  useEffect(
    () => () => {
      if (loopTimerRef.current) clearTimeout(loopTimerRef.current);
    },
    [],
  );

  const noop = useCallback(() => {}, []);

  return (
    <Canvas
      camera={{
        position: layout.cameraPos,
        fov: 45,
        near: layout.near,
        far: layout.far,
      }}
      style={{ background: "#F5F5F3" }}
    >
      <ambientLight intensity={0.5} />
      <directionalLight position={[5, 8, 3]} intensity={0.8} />
      <Environment preset="studio" environmentIntensity={0.3} />
      <GroundPlane
        groundY={layout.groundY}
        cellSize={layout.gridCell}
        sectionSize={layout.gridSection}
      />

      <AnimationController
        parts={parts}
        stepOrder={stepOrder}
        steps={steps}
        exploded={false}
        animStateRef={anim.animStateRef}
        renderStatesRef={anim.renderStatesRef}
        scrubberProgressRef={anim.scrubberProgressRef}
        onPhaseChange={onPhaseChange}
        executionActive={false}
        executionState={idleExecState}
        executionAnimRef={executionAnimRef}
      />

      {parts.map((part) => (
        <PartMesh
          key={part.id}
          part={part}
          renderStatesRef={anim.renderStatesRef}
          selectedStepId={null}
          firstStepIdForPart={partToStepId[part.id] ?? null}
          wireframeOverlay={false}
          colorMode="original"
          onClick={noop}
        />
      ))}

      <OrbitControls
        enableZoom={false}
        enablePan={false}
        autoRotate
        autoRotateSpeed={0.3}
        enableDamping
        dampingFactor={0.1}
      />
    </Canvas>
  );
}
