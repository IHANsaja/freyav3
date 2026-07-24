"use client";

import { Component, ReactNode, Suspense, useEffect, useRef } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import * as THREE from "three";
import type { AvatarIntent } from "../../hooks/useFreyaSocket";
import type { ExpressionEvent } from "../avatar/AvatarController";
import FreyaAvatar from "./FreyaAvatar";

interface PortraitSceneProps {
  state: string;
  avatarIntent: AvatarIntent | null;
  /** Fires false once the GLB is on screen; true while still streaming in. */
  onLoading: (loading: boolean) => void;
  /** Fires when WebGL or the GLB fails — parent swaps in the fallback. */
  onError: () => void;
  /** Bubbles the AvatarController's expression state up so the orb scene can
   *  react (matching accent color + particle-burst transition). */
  onExpressionChange: (e: ExpressionEvent | null) => void;
}

/** Reports Suspense resolution upward without rendering anything. */
function LoadSentinel({ onLoading }: { onLoading: (l: boolean) => void }) {
  useEffect(() => {
    onLoading(false);
    return () => onLoading(true);
  }, [onLoading]);
  return null;
}

/**
 * Cursor-aware rig: eases the whole figure's yaw/pitch a few degrees toward
 * the pointer while it's anywhere over the window — aware, not robotic. The
 * AvatarController's own procedural layer keeps breathing/sway underneath.
 */
function PortraitRig({ children }: { children: ReactNode }) {
  const group = useRef<THREE.Group>(null!);
  const target = useRef({ yaw: 0, pitch: 0 });

  useEffect(() => {
    const onMove = (e: PointerEvent) => {
      const nx = (e.clientX / window.innerWidth) * 2 - 1;
      const ny = (e.clientY / window.innerHeight) * 2 - 1;
      target.current.yaw = nx * 0.12; // ~±7°
      target.current.pitch = ny * 0.06;
    };
    window.addEventListener("pointermove", onMove, { passive: true });
    return () => window.removeEventListener("pointermove", onMove);
  }, []);

  useFrame((_, delta) => {
    if (!group.current) return;
    const k = Math.min(1, delta * 4);
    // -0.35 base yaw = the 3/4 portrait angle from the reference.
    group.current.rotation.y = THREE.MathUtils.lerp(group.current.rotation.y, -0.35 + target.current.yaw, k);
    group.current.rotation.x = THREE.MathUtils.lerp(group.current.rotation.x, target.current.pitch, k);
  });

  return <group ref={group}>{children}</group>;
}

/** Catches GLB/WebGL failures so the card can degrade to its static state. */
class PortraitErrorBoundary extends Component<{ onError: () => void; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch() {
    this.props.onError();
  }
  render() {
    return this.state.failed ? null : this.props.children;
  }
}

/**
 * Dedicated portrait viewport: head/shoulders 3/4 crop of the Freya GLB with
 * a crimson rim light silhouetting her against the near-black card. No
 * postprocessing — scanlines/vignette are CSS overlays in PortraitCard.
 */
export default function PortraitScene({
  state,
  avatarIntent,
  onLoading,
  onError,
  onExpressionChange,
}: PortraitSceneProps) {
  return (
    <PortraitErrorBoundary onError={onError}>
      <Canvas
        camera={{ position: [-0.8, 0.40, 1.2], fov: 30 }}
        dpr={[1, 1.5]}
        gl={{ antialias: false, powerPreference: "high-performance" }}
        onCreated={({ camera }) => camera.lookAt(0, 0.58, 0)}
        style={{ width: "100%", height: "100%", background: "transparent" }}
      >
        {/* Key rim: hot red from behind-left so her edges glow */}
        <directionalLight position={[-1.5, 0.8, -1]} intensity={2.5} color="#22e0a0" />
        {/* Low cool fill from the front so the face reads */}
        <directionalLight position={[1, 1.5, 2]} intensity={0.5} color="#aab4cc" />
        <ambientLight intensity={0.25} />

        <Suspense fallback={null}>
          <PortraitRig>
            <FreyaAvatar state={state} avatarIntent={avatarIntent} onExpression={onExpressionChange} />
          </PortraitRig>
          <LoadSentinel onLoading={onLoading} />
        </Suspense>
      </Canvas>
    </PortraitErrorBoundary>
  );
}
