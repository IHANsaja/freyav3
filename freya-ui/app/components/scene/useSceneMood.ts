"use client";

import { useEffect, useRef, useState } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";
import type { AvatarIntent } from "../../hooks/useFreyaSocket";
import type { PersonaPayload } from "../../types/events";
import { ExpressionAccent } from "../avatar/manifest";

export type VisualState = "idle" | "listening" | "speaking" | "interrupted" | "thinking" | "working";

const TARGETS: Record<VisualState, { amp: number; speed: number; glow: number; spin: number }> = {
  idle: { amp: 0.1, speed: 0.35, glow: 0.25, spin: 0.06 },
  listening: { amp: 0.18, speed: 0.75, glow: 0.55, spin: 0.14 },
  speaking: { amp: 0.42, speed: 1.9, glow: 1.0, spin: 0.32 },
  interrupted: { amp: 0.05, speed: 2.4, glow: 0.14, spin: 0.03 },
  thinking: { amp: 0.08, speed: 0.5, glow: 0.35, spin: 0.04 },
  working: { amp: 0.26, speed: 1.3, glow: 0.7, spin: 0.5 },
};

const DANCE_TARGET = { amp: 0.55, speed: 2.6, glow: 1.25, spin: 1.5 };

export interface SceneMood {
  amp: number;
  speed: number;
  glow: number;
  spin: number;
  time: number;
  dancing: boolean;
  color: THREE.Color;
}

/**
 * Ported from the old FreyaCore's TARGETS/expression-accent logic. Drives a
 * mutable ref every frame (no React state churn) that HoloPlatform,
 * ParticleField, and VoidBackground all read to make the whole scene
 * "breathe" in sync with session state, avatar intents, and persona theming.
 */
export function useSceneMood(
  state: string,
  avatarIntent: AvatarIntent | null,
  persona: PersonaPayload | null | undefined,
  expressionAccent: ExpressionAccent | null,
  expressionIntensity: number
) {
  const moodRef = useRef<SceneMood>({
    amp: 0.1,
    speed: 0.35,
    glow: 0.25,
    spin: 0.06,
    time: 0,
    dancing: false,
    color: new THREE.Color("#0f9c6e"),
  });

  const [dancing, setDancing] = useState(false);
  const [override, setOverride] = useState<VisualState | null>(null);

  useEffect(() => {
    if (!avatarIntent) return;
    if (avatarIntent.intent === "state") {
      if (avatarIntent.name === "dance") {
        setDancing(true);
        const timer = setTimeout(() => setDancing(false), avatarIntent.durationMs ?? 10000);
        return () => clearTimeout(timer);
      }
      if (avatarIntent.name === "thinking" || avatarIntent.name === "working") {
        setOverride(avatarIntent.name as VisualState);
      } else {
        setOverride(null);
      }
    }
  }, [avatarIntent]);

  useEffect(() => {
    if (state === "speaking" || state === "interrupted") setOverride(null);
  }, [state]);

  const sessionVisual: VisualState =
    state === "listening" || state === "speaking" || state === "interrupted" || state === "thinking" ? (state as VisualState) : "idle";
  const visual = override ?? sessionVisual;

  useFrame((_, delta) => {
    const mood = moodRef.current;
    mood.time += delta;
    mood.dancing = dancing;

    const base = dancing ? DANCE_TARGET : TARGETS[visual];
    const boost = expressionAccent
      ? {
          amp: expressionAccent.ampBoost * expressionIntensity,
          speed: expressionAccent.speedBoost * expressionIntensity,
          glow: expressionAccent.glowBoost * expressionIntensity,
        }
      : { amp: 0, speed: 0, glow: 0 };

    const personaGlow = persona?.theme?.glow ?? 1;
    const coreParams = persona?.theme?.coreParams ?? {};
    const target = {
      amp: Math.max(0.02, (coreParams.amp ?? base.amp) + boost.amp),
      speed: Math.max(0.1, (coreParams.speed ?? base.speed) + boost.speed),
      glow: Math.max(0.05, (base.glow + boost.glow) * personaGlow),
      spin: base.spin,
    };

    const k = Math.min(1, delta * 3.2);
    mood.amp = THREE.MathUtils.lerp(mood.amp, target.amp, k);
    mood.speed = THREE.MathUtils.lerp(mood.speed, target.speed, k);
    mood.spin = target.spin;

    const pulse = dancing ? 1 + Math.sin(mood.time * 6.0) * 0.25 : 1;
    mood.glow = THREE.MathUtils.lerp(mood.glow, target.glow * pulse, k);

    const restColor = persona?.theme?.accent ?? "#0f9c6e";
    const targetColor = expressionAccent ? new THREE.Color(expressionAccent.accent) : new THREE.Color(restColor);
    mood.color.lerp(targetColor, k * 0.6);
  });

  return moodRef;
}
