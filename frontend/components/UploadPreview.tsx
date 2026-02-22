"use client";

import { Suspense, useMemo, useRef } from "react";
import { Canvas } from "@react-three/fiber";
import { Environment } from "@react-three/drei";
import type { Assembly } from "@/lib/types";
import type { PartRenderState } from "@/lib/animation";
import { PartMesh } from "./viewer/PartMesh";
import { GroundPlane } from "./viewer/GroundPlane";

interface SceneLayout {
  cameraPos: [number, number, number];
  target: [number, number, number];
  near: number;
  far: number;
  groundY: number;
  gridCell: number;
  gridSection: number;
}

const DEFAULTS: SceneLayout = {
  cameraPos: [0.15, 0.12, 0.15],
  target: [0, 0.02, 0],
  near: 0.001,
  far: 10,
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
  const radius = Math.max(maxX - minX, maxY - minY, maxZ - minZ) * 0.75;

  if (radius < 0.001) return DEFAULTS;

  return {
    cameraPos: [cx + radius * 1.5, cy + radius * 1.2, cz + radius * 1.5],
    target: [cx, cy, cz],
    near: radius * 0.001,
    far: radius * 40,
    groundY: minY - radius * 0.02,
    gridCell: radius * 0.04,
    gridSection: radius * 0.2,
  };
}

interface UploadPreviewProps {
  assembly: Assembly;
}

export function UploadPreview({ assembly }: UploadPreviewProps) {
  const parts = useMemo(() => Object.values(assembly.parts), [assembly.parts]);
  const layout = useMemo(() => computeLayout(parts), [parts]);

  // Empty ref — PartMesh defaults to assembled position + full opacity
  const renderStatesRef = useRef<Record<string, PartRenderState>>({});

  return (
    <Canvas
      camera={{
        position: layout.cameraPos,
        fov: 45,
        near: layout.near,
        far: layout.far,
      }}
      style={{
        height: 200,
        borderRadius: 8,
        background: "radial-gradient(ellipse at 45% 40%, #FAF9F7 0%, #F0EDE8 100%)",
      }}
    >
      <ambientLight intensity={0.4} />
      <directionalLight position={[5, 8, 3]} intensity={0.7} castShadow />
      <Environment preset="studio" environmentIntensity={0.3} />

      <GroundPlane
        groundY={layout.groundY}
        cellSize={layout.gridCell}
        sectionSize={layout.gridSection}
      />

      <Suspense fallback={null}>
        {parts.map((part) => (
          <PartMesh
            key={part.id}
            part={part}
            renderStatesRef={renderStatesRef}
            selectedStepId={null}
            firstStepIdForPart={null}
            wireframeOverlay={false}
            colorMode="original"
            onClick={() => {}}
          />
        ))}
      </Suspense>
    </Canvas>
  );
}
