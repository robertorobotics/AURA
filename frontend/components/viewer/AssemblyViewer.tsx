"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Canvas, useThree } from "@react-three/fiber";
import { OrbitControls, Environment } from "@react-three/drei";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import type { PerspectiveCamera } from "three";
import { useAssembly } from "@/context/AssemblyContext";
import { useExecution } from "@/context/ExecutionContext";
import { partStepIndex } from "@/lib/animation";
import { useAnimationControls } from "@/lib/useAnimationControls";
import { GroundPlane } from "./GroundPlane";
import { PartMesh } from "./PartMesh";
import { ApproachVector } from "./ApproachVector";
import { AnimationController } from "./AnimationController";
import { ViewerControls } from "./ViewerControls";
import { AnimationTimeline } from "./AnimationTimeline";

// ---------------------------------------------------------------------------
// Camera helper — updates camera + controls when assembly changes
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

function CameraSetup({
  layout,
  controlsRef,
}: {
  layout: SceneLayout;
  controlsRef: React.RefObject<OrbitControlsImpl | null>;
}) {
  const { camera } = useThree();
  const prevAssemblyKey = useRef("");

  // Derive a key from the layout to detect assembly changes
  const layoutKey = `${layout.cameraPos.join(",")}|${layout.target.join(",")}`;

  useEffect(() => {
    if (layoutKey === prevAssemblyKey.current) return;
    prevAssemblyKey.current = layoutKey;

    camera.position.set(...layout.cameraPos);
    (camera as PerspectiveCamera).near = layout.near;
    (camera as PerspectiveCamera).far = layout.far;
    camera.updateProjectionMatrix();

    if (controlsRef.current) {
      controlsRef.current.target.set(...layout.target);
      controlsRef.current.maxDistance = layout.maxDist;
      controlsRef.current.update();
    }
  }, [layoutKey, layout, camera, controlsRef]);

  return null;
}

// ---------------------------------------------------------------------------
// Compute scene layout from assembly parts
// ---------------------------------------------------------------------------

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
// AssemblyViewer
// ---------------------------------------------------------------------------

export function AssemblyViewer() {
  const { assembly, selectedStepId, selectStep } = useAssembly();
  const { executionState } = useExecution();
  const controlsRef = useRef<OrbitControlsImpl>(null);

  const [exploded, setExploded] = useState(false);
  const [wireframe, setWireframe] = useState(false);

  const parts = useMemo(() => (assembly ? Object.values(assembly.parts) : []), [assembly]);
  const stepOrder = assembly?.stepOrder ?? [];
  const steps = assembly?.steps ?? {};
  const totalSteps = stepOrder.length;

  const anim = useAnimationControls(assembly?.id, totalSteps);

  const layout = useMemo(() => computeLayout(parts), [parts]);

  // Pre-compute part → first step id mapping
  const partToStepId = useMemo(() => {
    const map: Record<string, string | null> = {};
    if (!assembly) return map;
    for (const part of parts) {
      const idx = partStepIndex(part.id, assembly.stepOrder, assembly.steps);
      map[part.id] = idx >= 0 ? (assembly.stepOrder[idx] ?? null) : null;
    }
    return map;
  }, [assembly, parts]);

  // Force idle during live execution
  useEffect(() => {
    if (executionState.phase === "running" || executionState.phase === "paused") {
      anim.forceIdle();
    }
  }, [executionState.phase, anim]);

  const handlePartClick = useCallback(
    (partId: string) => {
      if (!assembly) return;
      const stepId = assembly.stepOrder.find((sid) => assembly.steps[sid]?.partIds.includes(partId));
      selectStep(stepId ?? null);
    },
    [assembly, selectStep],
  );

  return (
    <div className="relative h-full w-full">
      <Canvas
        camera={{ position: layout.cameraPos, fov: 45, near: layout.near, far: layout.far }}
        style={{ background: "#F5F5F3" }}
      >
        <CameraSetup layout={layout} controlsRef={controlsRef} />

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
          exploded={exploded}
          animStateRef={anim.animStateRef}
          renderStatesRef={anim.renderStatesRef}
          scrubberProgressRef={anim.scrubberProgressRef}
          onPhaseChange={anim.onPhaseChange}
        />

        {assembly &&
          parts.map((part) => (
            <group key={part.id}>
              <PartMesh
                part={part}
                renderStatesRef={anim.renderStatesRef}
                selectedStepId={selectedStepId}
                firstStepIdForPart={partToStepId[part.id] ?? null}
                wireframeOverlay={wireframe}
                onClick={() => handlePartClick(part.id)}
              />
              {selectedStepId === partToStepId[part.id] && part.graspPoints[0] && (
                <ApproachVector
                  origin={(part.position as [number, number, number]) ?? [0, 0, 0]}
                  direction={
                    (part.graspPoints[0].approach as [number, number, number]) ?? [0, -1, 0]
                  }
                  length={layout.gridSection}
                />
              )}
            </group>
          ))}

        <OrbitControls
          ref={controlsRef}
          enableDamping
          dampingFactor={0.1}
          minDistance={layout.near * 10}
          maxDistance={layout.maxDist}
          makeDefault
        />
      </Canvas>

      <ViewerControls
        exploded={exploded}
        onToggleExplode={() => setExploded((e) => !e)}
        wireframe={wireframe}
        onToggleWireframe={() => setWireframe((w) => !w)}
        animating={anim.isAnimating}
        paused={anim.isPaused}
        onToggleAnimation={anim.toggleAnimation}
        onStepForward={anim.stepForward}
        onStepBackward={anim.stepBackward}
        onResetView={() => controlsRef.current?.reset()}
        onReplayDemo={anim.replayDemo}
        demoPlayed={anim.demoPlayed}
      />

      {(anim.isAnimating || anim.demoPlayed) && (
        <AnimationTimeline
          totalSteps={totalSteps}
          scrubberProgressRef={anim.scrubberProgressRef}
          onScrub={anim.scrub}
          onScrubStart={anim.scrubStart}
          onScrubEnd={anim.scrubEnd}
        />
      )}
    </div>
  );
}
