"use client";

import { Suspense, useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { Edges, useGLTF } from "@react-three/drei";
import type { Group, Material, MeshStandardMaterial } from "three";
import { Mesh } from "three";
import type { Part } from "@/lib/types";
import type { PartRenderState } from "@/lib/animation";
import { GraspPoint } from "./GraspPoint";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const GHOST_COLOR = "#D4D4D0";
const COMPLETE_COLOR = "#C8C8C4";
const ACCENT_COLOR = "#E05A1A";

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function PlaceholderGeometry({ geometry, dimensions }: { geometry: string; dimensions: number[] }) {
  switch (geometry) {
    case "cylinder":
      return <cylinderGeometry args={[dimensions[0], dimensions[0], dimensions[1], 32]} />;
    case "sphere":
      return <sphereGeometry args={[dimensions[0], 32, 32]} />;
    default:
      return <boxGeometry args={[dimensions[0], dimensions[1], dimensions[2]]} />;
  }
}

function GlbMesh({ url }: { url: string }) {
  const fullUrl = url.startsWith("http") ? url : `${API_BASE}${url}`;
  const { scene } = useGLTF(fullUrl);

  // Clone scene with independent materials per instance
  const cloned = useMemo(() => {
    const c = scene.clone();
    c.traverse((child) => {
      if ((child as Mesh).isMesh) {
        const m = child as Mesh;
        m.material = (m.material as Material).clone();
      }
    });
    return c;
  }, [scene]);

  return <primitive object={cloned} />;
}

// ---------------------------------------------------------------------------
// PartMesh
// ---------------------------------------------------------------------------

interface PartMeshProps {
  part: Part;
  renderStatesRef: React.RefObject<Record<string, PartRenderState>>;
  selectedStepId: string | null;
  firstStepIdForPart: string | null;
  wireframeOverlay: boolean;
  onClick: () => void;
}

export function PartMesh({
  part,
  renderStatesRef,
  selectedStepId,
  firstStepIdForPart,
  wireframeOverlay,
  onClick,
}: PartMeshProps) {
  const groupRef = useRef<Group>(null);
  const matRef = useRef<MeshStandardMaterial>(null);
  const dims = part.dimensions ?? [0.05, 0.05, 0.05];
  const hasGlb = !!part.meshFile;

  // Track visual state for conditional rendering (edges, grasps)
  const visualRef = useRef<"ghost" | "active" | "complete">("complete");

  useFrame(({ clock }) => {
    const rs = renderStatesRef.current?.[part.id];
    if (!groupRef.current || !rs) return;

    // Position
    groupRef.current.position.set(rs.position[0], rs.position[1], rs.position[2]);

    // Determine effective state — selection overrides animation
    const isSelected = selectedStepId != null && selectedStepId === firstStepIdForPart;
    const effectiveState = isSelected ? "active" : rs.visualState;
    visualRef.current = effectiveState;

    // Opacity — pulse for active
    const isGhost = effectiveState === "ghost";
    let opacity = rs.opacity;
    if (effectiveState === "active") {
      opacity = 0.85 + 0.15 * Math.sin(clock.elapsedTime * Math.PI);
    } else if (isGhost) {
      opacity = Math.min(opacity, 0.12);
    }

    const transparent = isGhost || effectiveState === "active" || opacity < 1;
    const wire = isGhost || wireframeOverlay;

    // Determine color
    let color: string;
    if (isGhost) {
      color = GHOST_COLOR;
    } else if (effectiveState === "complete" && !isSelected) {
      color = COMPLETE_COLOR;
    } else {
      color = part.color ?? "#B0AEA8";
    }

    if (hasGlb) {
      // GLB path: traverse all meshes in the loaded scene
      groupRef.current.traverse((child) => {
        if ((child as Mesh).isMesh) {
          const mat = (child as Mesh).material as MeshStandardMaterial;
          if (mat.color) {
            mat.opacity = opacity;
            mat.transparent = transparent;
            mat.wireframe = wire;
            if (isGhost) mat.color.set(GHOST_COLOR);
            else if (effectiveState === "complete" && !isSelected) mat.color.set(COMPLETE_COLOR);
          }
        }
      });
    } else {
      // Placeholder path: single material ref
      if (!matRef.current) return;
      matRef.current.opacity = opacity;
      matRef.current.transparent = transparent;
      matRef.current.wireframe = wire;
      matRef.current.color.set(color);
    }
  });

  const isSelected = selectedStepId != null && selectedStepId === firstStepIdForPart;
  const showGrasps = isSelected;

  return (
    <group
      ref={groupRef}
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
    >
      {hasGlb ? (
        <Suspense
          fallback={
            <mesh castShadow>
              <PlaceholderGeometry geometry={part.geometry ?? "box"} dimensions={dims} />
              <meshStandardMaterial color={part.color ?? "#B0AEA8"} roughness={0.6} metalness={0.1} />
            </mesh>
          }
        >
          <GlbMesh url={part.meshFile!} />
        </Suspense>
      ) : (
        <mesh castShadow>
          <PlaceholderGeometry geometry={part.geometry ?? "box"} dimensions={dims} />
          <meshStandardMaterial
            ref={matRef}
            color={part.color ?? "#B0AEA8"}
            roughness={0.6}
            metalness={0.1}
            transparent
            opacity={1}
          />
          {isSelected && <Edges color={ACCENT_COLOR} linewidth={2} />}
        </mesh>
      )}

      {showGrasps &&
        part.graspPoints.map((_, i) => (
          <GraspPoint key={i} position={[0, dims[1] ? dims[1] / 2 : 0.02, 0]} index={i} />
        ))}
    </group>
  );
}
