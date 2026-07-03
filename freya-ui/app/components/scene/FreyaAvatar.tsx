"use client";

import { useEffect, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { useGLTF, useAnimations } from "@react-three/drei";
import * as THREE from "three";
import type { AvatarIntent } from "../../hooks/useFreyaSocket";
import { AvatarController, ExpressionEvent } from "../avatar/AvatarController";
import { AVATAR_MODELS, DEFAULT_AVATAR, BaseState } from "../avatar/manifest";

interface FreyaAvatarProps {
    state: string; // socket state: idle | listening | speaking | interrupted
    avatarIntent: AvatarIntent | null;
    modelKey?: string;
    onExpression: (e: ExpressionEvent | null) => void;
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

/**
 * The GLB embodiment — moved verbatim from the old FreyaModel.tsx so the
 * AvatarController wiring (3-layer mixer, intent handling, look-at) keeps
 * working unchanged inside the unified HoloScene canvas.
 */
export default function FreyaAvatar({ state, avatarIntent, modelKey, onExpression }: FreyaAvatarProps) {
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
