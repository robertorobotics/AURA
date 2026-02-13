"use client";

import { Suspense, useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { Edges, useGLTF } from "@react-three/drei";
import type { Group, Material, MeshStandardMaterial } from "three";
import { Box3, Mesh, Vector3 } from "three";
import type { Part } from "@/lib/types";
import type { PartRenderState } from "@/lib/animation";
import { GraspPoint } from "./GraspPoint";
import { GlbErrorBoundary, PlaceholderGeometry } from "./GlbErrorBoundary";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const GHOST_COLOR = "#D4D4D0";
const COMPLETE_COLOR = "#C8C8C4";
const ACCENT_COLOR = "#2563EB";

function GlbMesh({ url }: { url: string }) {
  const fullUrl = url.startsWith("http") ? url : `${API_BASE}${url}`;
  const { scene } = useGLTF(fullUrl);

  // Clone scene with independent materials, then recenter at local origin.
  // OCC tessellation may bake assembly-level transforms into GLB vertices;
  // Part.position (applied by the parent group) handles placement exclusively.
  const cloned = useMemo(() => {
    const c = scene.clone();
    c.traverse((child) => {
      if ((child as Mesh).isMesh) {
        const m = child as Mesh;
        m.material = (m.material as Material).clone();
      }
    });

    const box = new Box3().setFromObject(c);
    const center = box.getCenter(new Vector3());
    if (center.length() > 0.0001) {
      c.position.sub(center);
    }

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
    if (!groupRef.current) return;
    const rs: PartRenderState = renderStatesRef.current?.[part.id] ?? {
      position: (part.position as [number, number, number]) ?? [0, 0, 0],
      opacity: 1,
      visualState: "complete",
    };

    // Position + rotation
    groupRef.current.position.set(rs.position[0], rs.position[1], rs.position[2]);
    const rot = part.rotation;
    if (rot) {
      groupRef.current.rotation.set(rot[0], rot[1], rot[2]);
    }

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

    // Execution-mode overrides
    if (rs.colorOverride) color = rs.colorOverride;
    const emissive = rs.emissiveIntensity ?? 0;

    if (hasGlb) {
      // GLB path: traverse all meshes in the loaded scene
      groupRef.current.traverse((child) => {
        if ((child as Mesh).isMesh) {
          const mat = (child as Mesh).material as MeshStandardMaterial;
          if (mat.color) {
            mat.opacity = opacity;
            mat.transparent = transparent;
            mat.wireframe = wire;
            if (rs.colorOverride) mat.color.set(rs.colorOverride);
            else if (isGhost) mat.color.set(GHOST_COLOR);
            else if (effectiveState === "complete" && !isSelected) mat.color.set(COMPLETE_COLOR);
            if (mat.emissive) {
              mat.emissive.set(emissive > 0 ? color : "#000000");
              mat.emissiveIntensity = emissive;
            }
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
      matRef.current.emissive.set(emissive > 0 ? color : "#000000");
      matRef.current.emissiveIntensity = emissive;
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
        <GlbErrorBoundary
          geometry={part.geometry ?? "box"}
          dimensions={dims}
          meshUrl={part.meshFile!}
        >
          <Suspense
            fallback={
              <mesh castShadow receiveShadow>
                <PlaceholderGeometry geometry={part.geometry ?? "box"} dimensions={dims} />
                <meshStandardMaterial color={part.color ?? "#B0AEA8"} roughness={0.45} metalness={0.25} />
              </mesh>
            }
          >
            <GlbMesh url={part.meshFile!} />
          </Suspense>
        </GlbErrorBoundary>
      ) : (
        <mesh castShadow receiveShadow>
          <PlaceholderGeometry geometry={part.geometry ?? "box"} dimensions={dims} />
          <meshStandardMaterial
            ref={matRef}
            color={part.color ?? "#B0AEA8"}
            roughness={0.45}
            metalness={0.25}
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
