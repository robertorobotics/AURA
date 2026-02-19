"use client";

import { Component, type ReactNode } from "react";

// ---------------------------------------------------------------------------
// PlaceholderGeometry — shared between GLB fallback and placeholder path
// ---------------------------------------------------------------------------

export function PlaceholderGeometry({
  geometry,
  dimensions,
}: {
  geometry: string;
  dimensions: number[];
}) {
  switch (geometry) {
    case "cylinder":
      return <cylinderGeometry args={[dimensions[0], dimensions[0], dimensions[1], 32]} />;
    case "disc":
      // Disc → cylinder placeholder (flat circular shape: dims=[radius, height])
      return <cylinderGeometry args={[dimensions[0], dimensions[0], dimensions[1], 32]} />;
    case "sphere":
      return <sphereGeometry args={[dimensions[0], 32, 32]} />;
    case "plate":
      // Plate → box placeholder (flat rectangular shape: dims=[length, width, thickness])
      return <boxGeometry args={[dimensions[0], dimensions[1], dimensions[2]]} />;
    default:
      return <boxGeometry args={[dimensions[0], dimensions[1], dimensions[2]]} />;
  }
}

// ---------------------------------------------------------------------------
// GlbErrorBoundary — catches useGLTF load failures, renders placeholder
// ---------------------------------------------------------------------------

interface Props {
  children: ReactNode;
  geometry: string;
  dimensions: number[];
  meshUrl: string;
}

interface State {
  hasError: boolean;
}

export class GlbErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(error: Error): void {
    console.warn(`[PartMesh] GLB load failed for ${this.props.meshUrl}:`, error.message);
  }

  render() {
    if (this.state.hasError) {
      return (
        <mesh castShadow receiveShadow>
          <PlaceholderGeometry geometry={this.props.geometry} dimensions={this.props.dimensions} />
          <meshStandardMaterial color="#C47A32" roughness={0.5} metalness={0.2} transparent opacity={0.7} />
        </mesh>
      );
    }
    return this.props.children;
  }
}
