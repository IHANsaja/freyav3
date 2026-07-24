"use client";

import React, { useEffect, useRef, useState, Suspense } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { useGLTF, useAnimations, OrbitControls } from "@react-three/drei";
import * as THREE from "three";
import type { AvatarIntent } from "../hooks/useFreyaSocket";
import { AvatarController, ExpressionEvent } from "./avatar/AvatarController";
import { AVATAR_MODELS, DEFAULT_AVATAR, BaseState } from "./avatar/manifest";

interface FreyaModelProps {
    state: string; // socket state: idle | listening | speaking | interrupted
    avatarIntent: AvatarIntent | null;
    modelKey?: string;
}

/** Socket session states map to animation base states; richer states
 *  (thinking/working/dance/seated) arrive as avatar intents instead. */
function socketToBase(state: string): BaseState {
    switch (state) {
        case "speaking":
            return "speaking";
        case "listening":
        case "interrupted":
            return "listening";
        default:
            return "idle";
    }
}

function Model({
    state,
    avatarIntent,
    modelKey,
    onExpression,
}: FreyaModelProps & { onExpression: (e: ExpressionEvent | null) => void }) {
    const manifest = AVATAR_MODELS[modelKey ?? DEFAULT_AVATAR];
    const group = useRef<THREE.Group>(null!);
    const { scene, animations } = useGLTF(manifest.url);
    const { actions, mixer } = useAnimations(animations, group);
    const controllerRef = useRef<AvatarController | null>(null);
    const lastIntentSeq = useRef(0);

    // Instantiate the controller once mixer/actions/skeleton exist.
    useEffect(() => {
        if (!actions || !mixer || !group.current) return;
        const controller = new AvatarController(mixer, actions, manifest, group.current);
        controller.onExpressionChange = onExpression;
        controllerRef.current = controller;
        return () => {
            controller.dispose();
            controllerRef.current = null;
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [actions, mixer, manifest]);

    // Session state drives the base layer (free — no LLM involved). Dance and
    // other intent-driven states own the base layer while they're active.
    useEffect(() => {
        const c = controllerRef.current;
        if (!c) return;
        const keep = ["dance", "thinking", "working", "seated"];
        if (state === "speaking" || !keep.includes(c.getBaseState())) {
            c.setBaseState(socketToBase(state));
        }
    }, [state, actions]);

    // LLM intents layer on top.
    useEffect(() => {
        const c = controllerRef.current;
        if (!c || !avatarIntent || avatarIntent.seq === lastIntentSeq.current) return;
        lastIntentSeq.current = avatarIntent.seq;
        c.applyIntent(avatarIntent);
    }, [avatarIntent]);

    useFrame((rootState, delta) => {
        controllerRef.current?.update(delta, rootState.camera);
    });

    // Render the glTF scene generically so any manifest model works without
    // hardcoding node/material names.
    return (
        <group
            ref={group}
            dispose={null}
            position={[0, manifest.yOffset, 0]}
            scale={manifest.scale}
        >
            <primitive object={scene} />
        </group>
    );
}

useGLTF.preload(AVATAR_MODELS[DEFAULT_AVATAR].url);

export default function FreyaModel({ state, avatarIntent, modelKey }: FreyaModelProps) {
    const [accent, setAccent] = useState<string>("#0f9c6e");
    const [glow, setGlow] = useState(0);

    // Camera framing is per-model (each GLB has different real-world proportions
    // — a single global camera can't correctly frame both the old Mixamo rig and
    // the full-scale Blender export), so it's resolved once here alongside the
    // model itself rather than hardcoded on the Canvas.
    const manifest = AVATAR_MODELS[modelKey ?? DEFAULT_AVATAR];
    const cam = manifest.camera;

    const handleExpression = (e: ExpressionEvent | null) => {
        setAccent(e ? e.accent.accent : "#0f9c6e");
        setGlow(e ? e.accent.glowBoost * e.intensity : 0);
    };

    return (
        <div className="w-full h-full relative flex items-center justify-center">
            {/* Orbital rings, tinted by the live expression accent */}
            <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
                <div
                    className="w-[340px] h-[340px] rounded-full border animate-[spin_24s_linear_infinite] transition-colors duration-1000"
                    style={{ borderColor: `${accent}22` }}
                />
                <div className="absolute w-[390px] h-[390px] rounded-full border border-dashed border-outline-variant/10 animate-[spin_48s_linear_infinite_reverse]" />
            </div>

            <Canvas
                key={modelKey ?? DEFAULT_AVATAR}
                camera={{ position: cam.position, fov: cam.fov }}
                dpr={[1, 2]}
                style={{ width: "100%", height: "100%", background: "transparent" }}
            >
                <ambientLight intensity={0.7} />
                <directionalLight position={[2, 4, 3]} intensity={1.2} />
                <directionalLight position={[-2, 1, -1]} intensity={0.4} />
                {/* Accent spotlight follows the expression color */}
                <spotLight
                    position={[0, 5, 0]}
                    intensity={3 + glow * 4}
                    angle={0.6}
                    penumbra={1}
                    color={accent}
                />
                <Suspense fallback={null}>
                    <Model
                        state={state}
                        avatarIntent={avatarIntent}
                        modelKey={modelKey}
                        onExpression={handleExpression}
                    />
                </Suspense>
                <OrbitControls
                    enableZoom={false}
                    enablePan={false}
                    target={cam.target ?? [0, 0, 0]}
                    minPolarAngle={Math.PI / 3}
                    maxPolarAngle={Math.PI / 1.8}
                />
            </Canvas>
        </div>
    );
}
