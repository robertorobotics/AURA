"use client";

import { Suspense, useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { Edges, useGLTF } from "@react-three/drei";
import type { Group } from "three";
import {
  DoubleSide,
  EdgesGeometry,
  LineBasicMaterial,
  LineSegments,
  Mesh,
  MeshPhysicalMaterial,
} from "three";
import type { Part } from "@/lib/types";
import type { PartRenderState } from "@/lib/animation";
import { GraspPoint } from "./GraspPoint";
import { GlbErrorBoundary, PlaceholderGeometry } from "./GlbErrorBoundary";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const GHOST_COLOR = "#D4D4D0";
const ACCENT_COLOR = "#2563EB";

function GlbMesh({ url }: { url: string }) {
  const fullUrl = url.startsWith("http") ? url : `${API_BASE}${url}`;
  const { scene } = useGLTF(fullUrl);

  // Deep clone with independent geometry + material per mesh, so React
  // reconciliation cannot dispose shared WebGL buffers from the useGLTF cache.
  // GLB meshes are normalised to metres by the backend (tessellate_to_glb).
  const cloned = useMemo(() => {
    const root = scene.clone(true);
    root.traverse((child) => {
      child.frustumCulled = false;
      if ((child as Mesh).isMesh) {
        const m = child as Mesh;
        m.geometry = m.geometry.clone();
        const oldMat = m.material as MeshPhysicalMaterial;
        const newMat = new MeshPhysicalMaterial({
          color: oldMat.color,
          map: oldMat.map,
          roughness: oldMat.roughness ?? 0.4,
          metalness: oldMat.metalness ?? 0.15,
          clearcoat: 0.1,
          clearcoatRoughness: 0.4,
          envMapIntensity: 1.5,
          side: DoubleSide,
        });

        // Prevent black blobs: boost near-black colors to dark grey
        const hsl = { h: 0, s: 0, l: 0 };
        newMat.color.getHSL(hsl);
        if (hsl.l < 0.08) {
          newMat.color.setHSL(hsl.h, Math.min(hsl.s, 0.3), 0.15);
        }

        m.userData.originalColor = newMat.color.getHexString();
        m.material = newMat;

        // Edge lines for CAD-quality surface definition
        const edgesGeo = new EdgesGeometry(m.geometry, 25);
        const edgesMat = new LineBasicMaterial({
          color: 0x000000,
          transparent: true,
          opacity: 0.07,
        });
        const edgeLines = new LineSegments(edgesGeo, edgesMat);
        edgeLines.userData.isEdgeHelper = true;
        m.add(edgeLines);
      }
    });
    return root;
  }, [scene]);

  return <primitive object={cloned} castShadow receiveShadow />;
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
  colorMode: "original" | "distinct";
  visibilityColor?: string;
  onClick: () => void;
}

export function PartMesh({
  part,
  renderStatesRef,
  selectedStepId,
  firstStepIdForPart,
  wireframeOverlay,
  colorMode,
  visibilityColor,
  onClick,
}: PartMeshProps) {
  const groupRef = useRef<Group>(null);
  const matRef = useRef<MeshPhysicalMaterial>(null);
  const dims = part.dimensions ?? [0.05, 0.05, 0.05];
  const hasGlb = !!part.meshFile;

  // Track visual state for conditional rendering (edges, grasps)
  const visualRef = useRef<"ghost" | "active" | "complete">("complete");

  // Sync props into refs so useFrame always reads fresh values (avoids stale closures)
  const colorModeRef = useRef(colorMode);
  const visColorRef = useRef(visibilityColor);
  colorModeRef.current = colorMode;
  visColorRef.current = visibilityColor;

  useFrame(({ clock }) => {
    if (!groupRef.current) return;
    const rs: PartRenderState = renderStatesRef.current?.[part.id] ?? {
      position: (part.position as [number, number, number]) ?? [0, 0, 0],
      opacity: 1,
      visualState: "complete",
    };

    // Position + rotation
    groupRef.current.position.set(rs.position[0], rs.position[1], rs.position[2]);
    const rot = rs.rotation ?? part.rotation;
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

    // Determine color based on mode
    let color: string;
    if (isGhost) {
      color = GHOST_COLOR;
    } else if (colorModeRef.current === "distinct" && visColorRef.current) {
      color = visColorRef.current;
    } else {
      color = part.color ?? "#B0AEA8";
    }

    // Execution-mode overrides
    if (rs.colorOverride) color = rs.colorOverride;
    const emissive = rs.emissiveIntensity ?? 0;

    if (hasGlb) {
      // GLB path: traverse all meshes in the loaded scene
      groupRef.current.traverse((child) => {
        if (child.userData?.isEdgeHelper) {
          const lines = child as LineSegments;
          lines.visible = !isGhost && !wire;
          const lineMat = lines.material as LineBasicMaterial;
          if (isSelected && !isGhost) {
            lineMat.color.set(ACCENT_COLOR);
            lineMat.opacity = 0.4;
          } else {
            lineMat.color.set(0x000000);
            lineMat.opacity = 0.07;
          }
          return;
        }
        if ((child as Mesh).isMesh) {
          const mat = (child as Mesh).material as MeshPhysicalMaterial;
          if (mat.color) {
            const needsRecompile = mat.transparent !== transparent || mat.wireframe !== wire;
            mat.opacity = opacity;
            mat.transparent = transparent;
            mat.wireframe = wire;
            if (needsRecompile) mat.needsUpdate = true;
            // Color: override > ghost > distinct mode > restore original GLB color
            if (rs.colorOverride) mat.color.set(rs.colorOverride);
            else if (isGhost) mat.color.set(GHOST_COLOR);
            else if (colorModeRef.current === "distinct" && visColorRef.current) mat.color.set(visColorRef.current);
            else if ((child as Mesh).userData.originalColor) {
              mat.color.set(`#${(child as Mesh).userData.originalColor}`);
            }
            if (mat.emissive) {
              if (isSelected && !isGhost) {
                mat.emissive.set(ACCENT_COLOR);
                mat.emissiveIntensity = 0.3;
              } else if (emissive > 0) {
                mat.emissive.set(color);
                mat.emissiveIntensity = emissive;
              } else {
                mat.emissive.set("#000000");
                mat.emissiveIntensity = 0;
              }
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
      if (isSelected && !isGhost) {
        matRef.current.emissive.set(ACCENT_COLOR);
        matRef.current.emissiveIntensity = 0.3;
      } else if (emissive > 0) {
        matRef.current.emissive.set(color);
        matRef.current.emissiveIntensity = emissive;
      } else {
        matRef.current.emissive.set("#000000");
        matRef.current.emissiveIntensity = 0;
      }
    }
  });

  const isSelected = selectedStepId != null && selectedStepId === firstStepIdForPart;
  const showGrasps = isSelected;

  return (
    <group
      ref={groupRef}
      frustumCulled={false}
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
                <meshPhysicalMaterial color={part.color ?? "#B0AEA8"} roughness={0.4} metalness={0.15} clearcoat={0.1} clearcoatRoughness={0.4} envMapIntensity={1.5} />
              </mesh>
            }
          >
            <GlbMesh url={part.meshFile!} />
          </Suspense>
        </GlbErrorBoundary>
      ) : (
        <mesh castShadow receiveShadow>
          <PlaceholderGeometry geometry={part.geometry ?? "box"} dimensions={dims} />
          <meshPhysicalMaterial
            ref={matRef}
            color={part.color ?? "#B0AEA8"}
            roughness={0.4}
            metalness={0.15}
            clearcoat={0.1}
            clearcoatRoughness={0.4}
            envMapIntensity={1.5}
            transparent
            opacity={1}
          />
          <Edges
            color={isSelected ? ACCENT_COLOR : "#1a1a1a12"}
            linewidth={isSelected ? 2 : 1}
            threshold={25}
          />
        </mesh>
      )}

      {showGrasps &&
        part.graspPoints.map((gp, i) => (
          <GraspPoint
            key={i}
            position={
              gp.pose.length >= 3
                ? [gp.pose[0], gp.pose[1], gp.pose[2]]
                : [0, dims[1] ? dims[1] / 2 : 0.02, 0]
            }
            index={i}
          />
        ))}
    </group>
  );
}
