"use client";

// Renderless R3F component — smoothly dollies the camera to a 3/4 view
// on execution start, then gently nudges OrbitControls target toward
// the active part. Pauses nudge while user is interacting.

import { useEffect, useMemo, useRef, useState } from "react";
import { useFrame } from "@react-three/fiber";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import type { Vec3 } from "@/lib/animation";
import { easeInOut } from "@/lib/animation";
import type { ExecutionAnimState } from "@/lib/executionAnimation";

interface ExecutionCameraControllerProps {
  controlsRef: React.RefObject<OrbitControlsImpl | null>;
  executionActive: boolean;
  executionAnimRef: React.RefObject<ExecutionAnimState>;
  assemblyCenter: Vec3;
  assemblyRadius: number;
  workspaceRadius: number;
  currentPartPosition: Vec3 | null;
}

const NUDGE_FACTOR = 0.02;
const DOLLY_FRAMES = 60; // ~1 second at 60fps

export function ExecutionCameraController({
  controlsRef,
  executionActive,
  executionAnimRef,
  assemblyCenter,
  assemblyRadius,
  workspaceRadius,
  currentPartPosition,
}: ExecutionCameraControllerProps) {
  const initialSetRef = useRef(false);
  const [userInteracting, setUserInteracting] = useState(false);
  const timeoutRef = useRef<ReturnType<typeof setTimeout>>(undefined);
  const dollyProgressRef = useRef(0);
  const dollyStartPosRef = useRef<Vec3 | null>(null);

  // Ideal 3/4 camera position for execution viewing
  const idealCameraPos = useMemo<Vec3>(() => {
    const [cx, cy, cz] = assemblyCenter;
    const r = workspaceRadius;
    return [cx + r * 0.8, cy + r * 0.6, cz + r * 0.8];
  }, [assemblyCenter, workspaceRadius]);

  // Track user interaction with orbit controls
  useEffect(() => {
    const controls = controlsRef.current;
    if (!controls) return;
    const onStart = () => {
      clearTimeout(timeoutRef.current);
      setUserInteracting(true);
    };
    const onEnd = () => {
      timeoutRef.current = setTimeout(() => setUserInteracting(false), 2000);
    };
    controls.addEventListener("start", onStart);
    controls.addEventListener("end", onEnd);
    return () => {
      controls.removeEventListener("start", onStart);
      controls.removeEventListener("end", onEnd);
      clearTimeout(timeoutRef.current);
    };
  }, [controlsRef]);

  // Set initial camera target + start dolly on execution start
  useEffect(() => {
    if (!executionActive) {
      initialSetRef.current = false;
      dollyProgressRef.current = 0;
      dollyStartPosRef.current = null;
      return;
    }
    if (initialSetRef.current) return;
    initialSetRef.current = true;

    const controls = controlsRef.current;
    if (!controls) return;

    // Capture current camera position as dolly start
    const cam = controls.object;
    dollyStartPosRef.current = [cam.position.x, cam.position.y, cam.position.z];
    dollyProgressRef.current = 0;

    // Snap target to assembly center immediately
    controls.target.set(assemblyCenter[0], assemblyCenter[1], assemblyCenter[2]);
    controls.update();
  }, [executionActive, controlsRef, assemblyCenter]);

  useFrame(() => {
    if (!executionActive) return;
    const controls = controlsRef.current;
    const state = executionAnimRef.current;
    if (!controls || !state) return;

    // Camera dolly animation (~1 second)
    if (dollyStartPosRef.current && dollyProgressRef.current < 1) {
      dollyProgressRef.current = Math.min(1, dollyProgressRef.current + 1 / DOLLY_FRAMES);
      const t = easeInOut(dollyProgressRef.current);
      const start = dollyStartPosRef.current;
      const cam = controls.object;
      cam.position.x = start[0] + (idealCameraPos[0] - start[0]) * t;
      cam.position.y = start[1] + (idealCameraPos[1] - start[1]) * t;
      cam.position.z = start[2] + (idealCameraPos[2] - start[2]) * t;
    }

    // Gentle target nudge toward active part (skip if user is interacting)
    if (userInteracting) return;
    if (!currentPartPosition) return;
    const ct = controls.target;
    ct.x += (currentPartPosition[0] - ct.x) * NUDGE_FACTOR;
    ct.y += (currentPartPosition[1] - ct.y) * NUDGE_FACTOR;
    ct.z += (currentPartPosition[2] - ct.z) * NUDGE_FACTOR;
  });

  return null;
}
