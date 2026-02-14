"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Canvas, useThree } from "@react-three/fiber";
import { OrbitControls, Environment } from "@react-three/drei";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import { MOUSE, TOUCH } from "three";
import type { PerspectiveCamera } from "three";
import { useAssembly } from "@/context/AssemblyContext";
import { useExecution } from "@/context/ExecutionContext";
import { computeCentroid, computeAssemblyRadius, partStepIndex } from "@/lib/animation";
import type { Vec3 } from "@/lib/animation";
import { useAnimationControls } from "@/lib/useAnimationControls";
import { INITIAL_EXEC_ANIM } from "@/lib/executionAnimation";
import type { ExecutionAnimState } from "@/lib/executionAnimation";
import { GroundPlane } from "./GroundPlane";
import { PartMesh } from "./PartMesh";
import { ApproachVector } from "./ApproachVector";
import { AnimationController } from "./AnimationController";
import { ViewerControls } from "./ViewerControls";
import { AnimationTimeline } from "./AnimationTimeline";
import { RobotArm } from "./RobotArm";
import { ExecutionCameraController } from "./ExecutionCameraController";
import { ExecutionProgressHUD } from "./ExecutionProgressHUD";

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
    cameraPos: [cx + radius * 1.5, cy + radius * 1.2, cz + radius * 1.5],
    target: [cx, cy, cz],
    near: radius * 0.001,
    far: radius * 40,
    maxDist: radius * 15,
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

  // Geometry for execution animation
  const centroid = useMemo<Vec3>(() => computeCentroid(parts), [parts]);
  const assemblyRadius = useMemo(
    () => computeAssemblyRadius(parts, centroid),
    [parts, centroid],
  );

  // Execution animation state
  const executionAnimRef = useRef<ExecutionAnimState>({ ...INITIAL_EXEC_ANIM });
  const executionActive = executionState.phase === "running" || executionState.phase === "paused";

  // Robot arm base position (left of assembly, at ground level)
  const armBase = useMemo<Vec3>(
    () => [centroid[0] - assemblyRadius * 1.5, layout.groundY, centroid[2]],
    [centroid, assemblyRadius, layout.groundY],
  );

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

  // Force demo idle during live execution + reset execution anim state
  useEffect(() => {
    if (executionActive) {
      anim.forceIdle();
      executionAnimRef.current = { ...INITIAL_EXEC_ANIM };
    }
  }, [executionActive, anim]);

  // Keyboard shortcut: 'R' resets camera to default position
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "r" || e.key === "R") {
        if ((e.target as HTMLElement).tagName === "INPUT") return;
        controlsRef.current?.reset();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const handlePartClick = useCallback(
    (partId: string) => {
      if (!assembly) return;
      const stepId = assembly.stepOrder.find((sid) => assembly.steps[sid]?.partIds.includes(partId));
      selectStep(stepId ?? null);
    },
    [assembly, selectStep],
  );

  // Fit-to-view: recompute camera from current layout
  const handleFitToView = useCallback(() => {
    if (!controlsRef.current) return;
    const cam = controlsRef.current.object as PerspectiveCamera;
    cam.position.set(...layout.cameraPos);
    cam.near = layout.near;
    cam.far = layout.far;
    cam.updateProjectionMatrix();
    controlsRef.current.target.set(...layout.target);
    controlsRef.current.maxDistance = layout.maxDist * 2;
    controlsRef.current.update();
  }, [layout]);

  // Camera help toast — auto-dismiss after 4 seconds, re-show on assembly change
  const [showHelp, setShowHelp] = useState(false);
  useEffect(() => {
    if (!assembly) return;
    setShowHelp(true);
    const timer = setTimeout(() => setShowHelp(false), 4000);
    return () => clearTimeout(timer);
  }, [assembly?.id]);

  return (
    <div className="relative h-full w-full" style={{ touchAction: "none", overscrollBehavior: "none", boxShadow: "inset 0 1px 0 0 rgba(0,0,0,0.04)" }}>
      <Canvas
        camera={{ position: layout.cameraPos, fov: 45, near: layout.near, far: layout.far }}
        style={{ background: "radial-gradient(ellipse at 45% 40%, #FEFDFB 0%, #F9F7F3 80%)" }}
        shadows
        eventPrefix="offset"
      >
        <CameraSetup layout={layout} controlsRef={controlsRef} />

        <ambientLight intensity={0.4} />
        <directionalLight
          position={[5, 8, 3]}
          intensity={0.7}
          castShadow
          shadow-mapSize={[1024, 1024]}
          shadow-bias={-0.0005}
        />
        <directionalLight position={[-3, 4, -2]} intensity={0.3} />
        <directionalLight position={[0, -2, 5]} intensity={0.15} />
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
          executionActive={executionActive}
          executionState={executionState}
          executionAnimRef={executionAnimRef}
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

        <RobotArm
          basePosition={armBase}
          executionAnimRef={executionAnimRef}
          visible={executionActive}
          assemblyRadius={assemblyRadius}
        />

        <ExecutionCameraController
          controlsRef={controlsRef}
          executionActive={executionActive}
          executionAnimRef={executionAnimRef}
          assemblyCenter={centroid}
          assemblyRadius={assemblyRadius}
        />

        <OrbitControls
          ref={controlsRef}
          enableDamping
          dampingFactor={0.12}
          minDistance={layout.near * 5}
          maxDistance={layout.maxDist * 2}
          enablePan={true}
          screenSpacePanning
          panSpeed={1.5}
          rotateSpeed={0.8}
          zoomSpeed={1.2}
          minPolarAngle={0}
          maxPolarAngle={Math.PI}
          mouseButtons={{ LEFT: MOUSE.ROTATE, MIDDLE: MOUSE.DOLLY, RIGHT: MOUSE.PAN }}
          touches={{ ONE: TOUCH.ROTATE, TWO: TOUCH.DOLLY_PAN }}
          makeDefault
        />
      </Canvas>

      {executionActive && <ExecutionProgressHUD />}

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
        onFitToView={handleFitToView}
        onReplayDemo={anim.replayDemo}
        demoPlayed={anim.demoPlayed}
      />

      {showHelp && (
        <div className="pointer-events-none absolute bottom-14 left-1/2 -translate-x-1/2 rounded-md bg-text-primary/80 px-3 py-1.5 text-[11px] text-bg-primary backdrop-blur-sm">
          <span className="font-medium">Drag</span> orbit &middot;{" "}
          <span className="font-medium">Right-drag</span> pan &middot;{" "}
          <span className="font-medium">Scroll</span> zoom &middot;{" "}
          <span className="font-medium">R</span> reset
        </div>
      )}

      {!executionActive && (anim.isAnimating || anim.demoPlayed) && (
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
