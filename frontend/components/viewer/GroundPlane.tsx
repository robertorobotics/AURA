"use client";

import { Grid, ContactShadows } from "@react-three/drei";

interface GroundPlaneProps {
  groundY?: number;
  cellSize?: number;
  sectionSize?: number;
}

export function GroundPlane({
  groundY = -0.02,
  cellSize = 0.02,
  sectionSize = 0.1,
}: GroundPlaneProps) {
  return (
    <group>
      <Grid
        args={[2, 2]}
        cellSize={cellSize}
        cellColor="#E8E7E4"
        sectionSize={sectionSize}
        sectionColor="#D4D3CF"
        fadeDistance={sectionSize * 10}
        fadeStrength={1}
        infiniteGrid
        position={[0, groundY, 0]}
      />
      <ContactShadows
        position={[0, groundY + 0.001, 0]}
        opacity={0.25}
        scale={sectionSize * 5}
        blur={2}
        far={sectionSize * 1.5}
      />
    </group>
  );
}
