"use client";

import { memo, useEffect, useState } from "react";
import { Canvas } from "@react-three/fiber";
import type { MutableRefObject } from "react";
import type { AvatarIntent } from "../../hooks/useFreyaSocket";
import type { PersonaPayload } from "../../types/events";
import type { ExpressionEvent } from "../avatar/AvatarController";
import HoloPlatform from "./HoloPlatform";
import ParticleField from "./ParticleField";
import VoidBackground from "./VoidBackground";
import Effects from "./Effects";
import Orb, { type OrbFx } from "./Orb";
import OrbCameraRig from "./OrbCameraRig";
import { useSceneMood } from "./useSceneMood";
import type { HandGestureState } from "../../hooks/useHandGestures";

interface OrbSceneProps {
  state: string;
  avatarIntent: AvatarIntent | null;
  persona?: PersonaPayload | null;
  /** Latest expression from the portrait avatar — colors the orb + core
   *  light to match and (via fxRef.expressionBurst) triggers its particle
   *  dissolve/reform transition. */
  expression?: ExpressionEvent | null;
  fxRef: MutableRefObject<OrbFx>;
  /** Tracked webcam hand state — drives the camera orbit (OrbCameraRig reads
   *  only .present/.x/.y here; discrete gesture reactions are dispatched
   *  elsewhere via useGestureOrbBridge). */
  gestureRef: MutableRefObject<HandGestureState>;
}

// The orb floats at y≈0.45 with the projection dais beneath it, framed so the
// orb sits in the upper-center of the viewport, clear of the mode tabs /
// action buttons overlaid below. The camera orbits in response to tracked
// webcam hand movement (see OrbCameraRig) — there is no mouse-drag control.
const ORB_Y = 0.45;
const PLATFORM_Y = -0.55;

function SceneContents({ state, avatarIntent, persona, expression, fxRef }: OrbSceneProps) {
  // The orb has no avatar of its own — its expression accent rides in from
  // the portrait card's FreyaAvatar via the expression prop, same as
  // HoloScene wires expression → mood for the full-body embodiment.
  const moodRef = useSceneMood(
    state,
    avatarIntent,
    persona,
    expression?.accent ?? null,
    expression?.intensity ?? 0.7
  );

  const glowBoost = expression ? expression.accent.glowBoost * expression.intensity : 0;
  const coreColor = expression?.accent.accent ?? persona?.theme?.accent ?? "#ff2b3a";

  return (
    <>
      <ambientLight intensity={0.4} />
      {/* Crimson core-light so platform dust picks up the orb's glow —
          recolors to the active expression's accent, same as the orb itself. */}
      <pointLight position={[0, ORB_Y, 0]} intensity={1.4 + glowBoost * 2} distance={5} color={coreColor} />

      <VoidBackground moodRef={moodRef} />
      <HoloPlatform moodRef={moodRef} yOffset={PLATFORM_Y} />
      <ParticleField moodRef={moodRef} centerY={ORB_Y} />
      <Orb moodRef={moodRef} fxRef={fxRef} position={[0, ORB_Y, 0]} />

      <Effects />
    </>
  );
}

/** Full-bleed stage behind the HUD grid: nebula void, ring dais, particle
 *  stream, and the particle-orb AI core. Camera orbits via tracked webcam
 *  hand movement (OrbCameraRig) — no mouse-drag controls. */
function OrbScene(props: OrbSceneProps) {
  const [frameloop, setFrameloop] = useState<"always" | "never">("always");

  useEffect(() => {
    const onVis = () => setFrameloop(document.hidden ? "never" : "always");
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, []);

  return (
    <div className="w-full h-full relative">
      <Canvas
        frameloop={frameloop}
        camera={{ position: [0, 0.55, 4.6], fov: 42 }}
        dpr={[1, 1.5]}
        gl={{ antialias: false, powerPreference: "high-performance" }}
        onCreated={({ camera }) => camera.lookAt(0, 0.35, 0)}
        style={{ width: "100%", height: "100%", background: "transparent" }}
      >
        <SceneContents {...props} />
        <OrbCameraRig gestureRef={props.gestureRef} target={[0, ORB_Y, 0]} />
      </Canvas>
    </div>
  );
}

export default memo(OrbScene);
