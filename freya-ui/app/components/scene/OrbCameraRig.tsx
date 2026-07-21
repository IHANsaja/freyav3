"use client";

import { useEffect, useRef } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import * as THREE from "three";
import type { MutableRefObject } from "react";
import type { HandGestureState } from "../../hooks/useHandGestures";

const MIN_POLAR = Math.PI / 2.6;
const MAX_POLAR = Math.PI / 1.6;
// The orb scene's backdrop (VoidBackground's enclosing sphere, HoloPlatform's
// disc) is rotationally symmetric — unlike HoloScene's humanoid avatar, there's
// no "wrong side" to orbit to, so azimuth is left effectively unclamped.
const HAND_TO_AZIMUTH = Math.PI * 1.6;
const HAND_TO_POLAR = Math.PI * 1.0;
const SMOOTHING = 6; // higher = snappier, lower = smoother/laggier

interface OrbCameraRigProps {
  gestureRef: MutableRefObject<HandGestureState>;
  target?: [number, number, number];
}

/** Drives the orb scene's camera purely from tracked hand position — no mouse
 *  drag, no drei OrbitControls. Frame-to-frame hand movement (while a hand is
 *  present) is treated like a drag gesture: horizontal motion orbits azimuth,
 *  vertical motion orbits polar angle, both accumulated and smoothed. Only
 *  reads gestureRef.present/x/y — never .gesture — so continuous orbiting
 *  stays fully decoupled from discrete gesture-triggered reactions. */
export default function OrbCameraRig({ gestureRef, target = [0, 0.45, 0] }: OrbCameraRigProps) {
  const { camera } = useThree();

  const targetVec = useRef(new THREE.Vector3(...target));
  const radius = useRef(1);
  const azimuth = useRef(0);
  const polar = useRef(Math.PI / 2.4);
  const azimuthSmooth = useRef(0);
  const polarSmooth = useRef(Math.PI / 2.4);
  const lastHand = useRef<{ x: number; y: number } | null>(null);
  const initialized = useRef(false);

  useEffect(() => {
    targetVec.current.set(...target);
  }, [target]);

  useEffect(() => {
    // Decompose the camera's existing (locked) position into spherical
    // coordinates around the target so the rig picks up exactly where the
    // static framing left off — no jump cut when hand tracking engages.
    const offset = camera.position.clone().sub(targetVec.current);
    radius.current = offset.length();
    azimuth.current = Math.atan2(offset.x, offset.z);
    polar.current = Math.acos(THREE.MathUtils.clamp(offset.y / radius.current, -1, 1));
    azimuthSmooth.current = azimuth.current;
    polarSmooth.current = polar.current;
    initialized.current = true;
    // Only ever decompose once, from whatever the Canvas's declared camera
    // position was — not on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useFrame((_, delta) => {
    if (!initialized.current) return;
    const hand = gestureRef.current;

    if (hand.present) {
      if (lastHand.current) {
        const dx = hand.x - lastHand.current.x;
        const dy = hand.y - lastHand.current.y;
        azimuth.current -= dx * HAND_TO_AZIMUTH;
        polar.current = THREE.MathUtils.clamp(polar.current - dy * HAND_TO_POLAR, MIN_POLAR, MAX_POLAR);
      }
      lastHand.current = { x: hand.x, y: hand.y };
    } else {
      // Hand left the frame — hold the current orbit, and don't let the next
      // re-entry compute a delta against a stale position.
      lastHand.current = null;
    }

    const k = Math.min(1, delta * SMOOTHING);
    azimuthSmooth.current = THREE.MathUtils.lerp(azimuthSmooth.current, azimuth.current, k);
    polarSmooth.current = THREE.MathUtils.lerp(polarSmooth.current, polar.current, k);

    const r = radius.current;
    const az = azimuthSmooth.current;
    const pol = polarSmooth.current;
    camera.position.set(
      targetVec.current.x + r * Math.sin(pol) * Math.sin(az),
      targetVec.current.y + r * Math.cos(pol),
      targetVec.current.z + r * Math.sin(pol) * Math.cos(az)
    );
    camera.lookAt(targetVec.current);
  });

  return null;
}
