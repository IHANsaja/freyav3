import * as THREE from "three";
import type { AvatarIntentPayload } from "../../types/events";
import {
    AvatarModelManifest,
    BaseState,
    EXPRESSION_ACCENTS,
    ExpressionAccent,
} from "./manifest";

export interface ExpressionEvent {
    name: string;
    intensity: number;
    accent: ExpressionAccent;
}

const BASE_FADE_S = 0.4;
const GESTURE_FADE_S = 0.25;
const GESTURE_BASE_WEIGHT = 0.15; // base layer weight while a gesture plays
const TALK_CYCLE_MIN_S = 6;
const TALK_CYCLE_MAX_S = 9;
const LOOK_AT_MAX_RAD = 0.44; // ~25°

/**
 * Three-layer avatar animation controller. Plain TS (no React/R3F) so it can
 * be unit-tested against a bare AnimationMixer.
 *
 *  Layer 0 — base: exactly one looping clip, chosen per BaseState, crossfaded;
 *            never stopped, so the skeleton always has a pose (no T-pose ever).
 *  Layer 1 — gesture: LoopOnce clips weight-blended over the base, auto-fading
 *            back when finished; at most one queued replacement.
 *  Layer 2 — procedural: breathing, camera look-at, thinking tilt, idle sway —
 *            applied in update() AFTER the mixer has sampled the clips, every
 *            frame unconditionally.
 */
export class AvatarController {
    private mixer: THREE.AnimationMixer;
    private actions: Record<string, THREE.AnimationAction | null>;
    private manifest: AvatarModelManifest;
    private bones: { head?: THREE.Object3D; neck?: THREE.Object3D; spine: THREE.Object3D[] };

    private baseState: BaseState = "idle";
    private baseAction: THREE.AnimationAction | null = null;
    private gestureAction: THREE.AnimationAction | null = null;
    private pendingGesture: string | null = null;

    private time = 0;
    private nextTalkSwitch = 0;
    private expression: { name: string; intensity: number } | null = null;
    private expressionUntil = 0;
    private danceUntil = 0;
    private stateBeforeDance: BaseState = "idle";

    /** Fired when the expression changes — FreyaCore/UI accents subscribe. */
    onExpressionChange?: (e: ExpressionEvent | null) => void;

    constructor(
        mixer: THREE.AnimationMixer,
        actions: Record<string, THREE.AnimationAction | null>,
        manifest: AvatarModelManifest,
        root: THREE.Object3D,
    ) {
        this.mixer = mixer;
        this.actions = actions;
        this.manifest = manifest;

        const find = (name: string) => {
            let found: THREE.Object3D | undefined;
            root.traverse((o) => {
                if (!found && o.name === name) found = o;
            });
            return found;
        };
        this.bones = {
            head: find(manifest.bones.head),
            neck: find(manifest.bones.neck),
            spine: manifest.bones.spine
                .map(find)
                .filter((b): b is THREE.Object3D => b !== undefined),
        };
        this.mixer.addEventListener("finished", this.onClipFinished);
        this.setBaseState("idle", true);
    }

    dispose() {
        this.mixer.removeEventListener("finished", this.onClipFinished);
    }

    // ── Layer 0: base state ────────────────────────────────────────────────

    setBaseState(state: BaseState, force = false) {
        if (!force && state === this.baseState) return;
        this.baseState = state;
        if (state === "speaking") this.scheduleTalkSwitch();
        this.playBaseClip(this.pickBaseClip(state), force);
    }

    getBaseState(): BaseState {
        return this.baseState;
    }

    private pickBaseClip(state: BaseState): string | null {
        const pool = this.manifest.base[state] ?? this.manifest.base.idle ?? [];
        if (pool.length === 0) return null;
        if (pool.length === 1) return pool[0];
        const current = this.baseAction?.getClip().name;
        const options = pool.filter((c) => c !== current);
        return options[Math.floor(Math.random() * options.length)] ?? pool[0];
    }

    private playBaseClip(clipName: string | null, snap = false) {
        const next = clipName ? this.actions[clipName] : null;
        if (!next || next === this.baseAction) return;
        next.setLoop(THREE.LoopRepeat, Infinity);
        next.enabled = true;
        next.reset().fadeIn(snap ? 0 : BASE_FADE_S).play();
        next.setEffectiveWeight(this.gestureAction ? GESTURE_BASE_WEIGHT : 1);
        if (this.baseAction) this.baseAction.fadeOut(snap ? 0 : BASE_FADE_S);
        this.baseAction = next;
    }

    private scheduleTalkSwitch() {
        this.nextTalkSwitch =
            this.time + TALK_CYCLE_MIN_S + Math.random() * (TALK_CYCLE_MAX_S - TALK_CYCLE_MIN_S);
    }

    // ── Layer 1: gestures ──────────────────────────────────────────────────

    playGesture(name: string) {
        const clipName = this.manifest.gestures[name];
        if (!clipName || !this.actions[clipName]) return;
        if (this.gestureAction) {
            // One pending replacement max — newest intent wins.
            this.pendingGesture = name;
            return;
        }
        this.startGesture(clipName);
    }

    private startGesture(clipName: string) {
        const action = this.actions[clipName];
        if (!action) return;
        action.setLoop(THREE.LoopOnce, 1);
        action.clampWhenFinished = true;
        action.enabled = true;
        action.reset().fadeIn(GESTURE_FADE_S).play();
        action.setEffectiveWeight(1);
        this.baseAction?.setEffectiveWeight(GESTURE_BASE_WEIGHT);
        this.gestureAction = action;
    }

    private onClipFinished = (e: { action: THREE.AnimationAction }) => {
        if (e.action !== this.gestureAction) return;
        e.action.fadeOut(GESTURE_FADE_S);
        this.gestureAction = null;
        this.baseAction?.setEffectiveWeight(1);
        if (this.pendingGesture) {
            const next = this.pendingGesture;
            this.pendingGesture = null;
            this.playGesture(next);
        }
    };

    // ── Intents from the backend ───────────────────────────────────────────

    applyIntent(intent: AvatarIntentPayload) {
        switch (intent.intent) {
            case "gesture":
            case "emphasis":
                this.playGesture(intent.name);
                break;
            case "expression":
                this.setExpression(intent.name, intent.intensity ?? 0.7);
                break;
            case "idle":
                // standing → idle, seated/attentive map to their own pools
                this.setBaseState(
                    intent.name === "standing" ? "idle" : (intent.name as BaseState),
                );
                break;
            case "state":
                if (intent.name === "dance") {
                    this.stateBeforeDance =
                        this.baseState === "dance" ? this.stateBeforeDance : this.baseState;
                    this.danceUntil = this.time + (intent.durationMs ?? 10000) / 1000;
                    this.setBaseState("dance");
                } else {
                    this.setBaseState(intent.name as BaseState);
                }
                break;
        }
    }

    setExpression(name: string, intensity: number) {
        const accent = EXPRESSION_ACCENTS[name];
        if (!accent) return;
        this.expression = { name, intensity };
        this.expressionUntil = this.time + 12; // expressions decay after ~12s
        this.onExpressionChange?.({ name, intensity, accent });
    }

    // ── Layer 2: procedural (every frame, after mixer.update) ─────────────

    update(dt: number, camera?: THREE.Camera) {
        this.time += dt;

        // Expression decay back to neutral.
        if (this.expression && this.time > this.expressionUntil) {
            this.expression = null;
            this.onExpressionChange?.(null);
        }

        // Dance auto-exit.
        if (this.baseState === "dance" && this.danceUntil > 0 && this.time > this.danceUntil) {
            this.danceUntil = 0;
            this.setBaseState(this.stateBeforeDance);
        }

        // Speaking: rotate through talk clips so long answers stay alive.
        if (this.baseState === "speaking" && this.time > this.nextTalkSwitch) {
            this.scheduleTalkSwitch();
            this.playBaseClip(this.pickBaseClip("speaking"));
        }

        const accent = this.expression ? EXPRESSION_ACCENTS[this.expression.name] : null;
        const breathScale = accent?.breathScale ?? 1;

        // Breathing on the spine — additive over what the clips sampled this
        // frame (the mixer rewrites bone rotations every frame, so these
        // offsets never accumulate).
        const breath = Math.sin(this.time * 1.7) * 0.02 * breathScale;
        for (const bone of this.bones.spine) {
            bone.rotation.x += breath;
        }

        // Head: look-at while listening/attentive, tilt while thinking, sway idle.
        const head = this.bones.head;
        if (head) {
            if (
                (this.baseState === "listening" || this.baseState === "attentive") &&
                camera
            ) {
                const camLocal = head.parent
                    ? head.parent.worldToLocal(camera.position.clone())
                    : camera.position.clone();
                const yaw = THREE.MathUtils.clamp(
                    Math.atan2(camLocal.x, camLocal.z) * 0.35,
                    -LOOK_AT_MAX_RAD,
                    LOOK_AT_MAX_RAD,
                );
                const pitch = THREE.MathUtils.clamp(
                    -Math.atan2(camLocal.y, Math.hypot(camLocal.x, camLocal.z)) * 0.3,
                    -0.2,
                    0.25,
                );
                head.rotation.y += yaw;
                head.rotation.x += pitch;
            } else if (this.baseState === "thinking") {
                head.rotation.z += 0.12;
                head.rotation.x += 0.1 + Math.sin(this.time * 0.6) * 0.02;
            } else if (this.baseState === "idle" || this.baseState === "seated") {
                head.rotation.y += Math.sin(this.time * 0.4) * 0.05;
            }
        }
    }
}
