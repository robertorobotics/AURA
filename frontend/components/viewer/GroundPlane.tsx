"use client";

import { useMemo } from "react";
import { Grid, ContactShadows, Line } from "@react-three/drei";

interface GroundPlaneProps {
  groundY?: number;
  cellSize?: number;
  sectionSize?: number;
  surfaceWidth?: number;
  surfaceDepth?: number;
  assemblyRadius?: number;
}

/** Generates points for a circle in the XZ plane at the given Y height. */
function circlePoints(
  radius: number,
  y: number,
  segments: number,
): [number, number, number][] {
  const pts: [number, number, number][] = [];
  for (let i = 0; i <= segments; i++) {
    const angle = (i / segments) * Math.PI * 2;
    pts.push([Math.cos(angle) * radius, y, Math.sin(angle) * radius]);
  }
  return pts;
}

export function GroundPlane({
  groundY = -0.02,
  cellSize = 0.02,
  sectionSize = 0.1,
  surfaceWidth = 0.5,
  surfaceDepth = 0.4,
  assemblyRadius,
}: GroundPlaneProps) {
  const surfaceZ = surfaceDepth / 4;
  const halfW = surfaceWidth / 2;
  const halfD = surfaceDepth / 2;

  // Rectangle edge as a closed loop (5 points)
  const edgePoints = useMemo<[number, number, number][]>(
    () => [
      [-halfW, groundY, surfaceZ - halfD],
      [halfW, groundY, surfaceZ - halfD],
      [halfW, groundY, surfaceZ + halfD],
      [-halfW, groundY, surfaceZ + halfD],
      [-halfW, groundY, surfaceZ - halfD],
    ],
    [halfW, halfD, groundY, surfaceZ],
  );

  // Assembly zone dashed ring
  const ringPoints = useMemo(
    () =>
      assemblyRadius && assemblyRadius > 0
        ? circlePoints(assemblyRadius * 1.2, groundY + 0.0005, 64)
        : null,
    [assemblyRadius, groundY],
  );

  return (
    <group>
      {/* Background grid — dimmed, infinite for spatial context */}
      <Grid
        args={[2, 2]}
        cellSize={cellSize}
        cellColor="#F0F0F0"
        sectionSize={sectionSize}
        sectionColor="#E4E4E8"
        fadeDistance={sectionSize * 5}
        fadeStrength={2}
        infiniteGrid
        position={[0, groundY, 0]}
      />

      {/* Work surface — bounded table rectangle */}
      <mesh
        position={[0, groundY, surfaceZ]}
        rotation={[-Math.PI / 2, 0, 0]}
        receiveShadow
      >
        <planeGeometry args={[surfaceWidth, surfaceDepth]} />
        <meshStandardMaterial color="#E8E6E1" roughness={0.85} metalness={0.05} />
      </mesh>

      {/* Surface edge lines */}
      <Line points={edgePoints} color="#C4C2BD" lineWidth={1} />

      {/* Contact shadows — covers work surface */}
      <ContactShadows
        position={[0, groundY + 0.001, surfaceZ]}
        opacity={0.45}
        scale={Math.max(surfaceWidth, surfaceDepth) * 1.2}
        blur={2.5}
        far={sectionSize * 2}
      />

      {/* Optional assembly zone indicator */}
      {ringPoints && (
        <Line
          points={ringPoints}
          color="#D0CEC8"
          lineWidth={1}
          dashed
          dashSize={0.008}
          gapSize={0.008}
        />
      )}
    </group>
  );
}
