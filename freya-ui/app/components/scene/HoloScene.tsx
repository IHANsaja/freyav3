"use client";

import { memo, Suspense, useCallback, useEffect, useState } from "react";
import { Canvas } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import type { AvatarIntent } from "../../hooks/useFreyaSocket";
import type { PersonaPayload } from "../../types/events";
import { AVATAR_MODELS, DEFAULT_AVATAR } from "../avatar/manifest";
import { ExpressionEvent } from "../avatar/AvatarController";
import FreyaAvatar from "./FreyaAvatar";
import HoloPlatform from "./HoloPlatform";
import ParticleField from "./ParticleField";
import VoidBackground from "./VoidBackground";
import Effects from "./Effects";
import { useSceneMood } from "./useSceneMood";

interface HoloSceneProps {
  state: string;
  avatarIntent: AvatarIntent | null;
  persona?: PersonaPayload | null;
  modelKey?: string;
}

function SceneContents({ state, avatarIntent, persona, modelKey }: HoloSceneProps) {
  const [expression, setExpression] = useState<ExpressionEvent | null>(null);
  const handleExpression = useCallback((e: ExpressionEvent | null) => setExpression(e), []);

  const moodRef = useSceneMood(state, avatarIntent, persona, expression?.accent ?? null, expression?.intensity ?? 0.7);

  const accentColor = expression ? expression.accent.accent : persona?.theme?.accent ?? "#0f9c6e";
  const glowBoost = expression ? expression.accent.glowBoost * expression.intensity : 0;

  const manifest = AVATAR_MODELS[modelKey ?? DEFAULT_AVATAR];

  return (
    <>
      <ambientLight intensity={0.7} />
      <directionalLight position={[2, 4, 3]} intensity={1.2} />
      <directionalLight position={[-2, 1, -1]} intensity={0.4} />
      <spotLight
        position={[0, 5, 0]}
        intensity={3 + glowBoost * 4}
        angle={0.6}
        penumbra={1}
        color={accentColor}
      />
      {/* Crimson under-glow rising from the holo platform */}
      <pointLight
        position={[0, manifest.yOffset - 0.05, 0]}
        intensity={1.5 + glowBoost * 2}
        distance={4}
        color={accentColor}
      />

      <VoidBackground moodRef={moodRef} />
      <HoloPlatform moodRef={moodRef} yOffset={manifest.yOffset} />
      <ParticleField moodRef={moodRef} centerY={manifest.yOffset + 1.1} />

      <Suspense fallback={null}>
        <FreyaAvatar
          state={state}
          avatarIntent={avatarIntent}
          modelKey={modelKey}
          onExpression={handleExpression}
        />
      </Suspense>

      <Effects />
    </>
  );
}

function HoloScene({ state, avatarIntent, persona, modelKey }: HoloSceneProps) {
  const key = modelKey ?? DEFAULT_AVATAR;
  const manifest = AVATAR_MODELS[key];
  const cam = manifest.hudCamera ?? manifest.camera;
  const [frameloop, setFrameloop] = useState<"always" | "never">("always");

  useEffect(() => {
    const onVis = () => setFrameloop(document.hidden ? "never" : "always");
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, []);

  return (
    <div className="w-full h-full relative">
      <Canvas
        key={key}
        frameloop={frameloop}
        camera={{ position: cam.position, fov: cam.fov }}
        dpr={[1, 1.5]}
        gl={{ antialias: false, powerPreference: "high-performance" }}
        style={{ width: "100%", height: "100%", background: "transparent" }}
      >
        <SceneContents state={state} avatarIntent={avatarIntent} persona={persona} modelKey={modelKey} />
        <OrbitControls
          enableZoom={false}
          enablePan={false}
          enableDamping
          target={cam.target ?? [0, 0, 0]}
          minPolarAngle={Math.PI / 2.6}
          maxPolarAngle={Math.PI / 1.9}
          minAzimuthAngle={-0.5}
          maxAzimuthAngle={0.5}
        />
      </Canvas>
    </div>
  );
}

export default memo(HoloScene);
