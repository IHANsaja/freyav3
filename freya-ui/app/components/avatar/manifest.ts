// Avatar model manifest — the contract between animation intents and the clips
// each GLB actually contains. The AvatarController is model-agnostic: swap in a
// new model (e.g. the Blender-authored FreyaV2.glb) by adding an entry here.

export type BaseState =
    | "idle" | "listening" | "speaking" | "thinking" | "working" | "dance"
    | "seated" | "attentive";

export interface AvatarModelManifest {
    /** URL under /public */
    url: string;
    /** Uniform scale + vertical offset applied to the scene root */
    scale: number;
    yOffset: number;
    /** Looping clip pools per base state (random pick; speaking cycles) */
    base: Partial<Record<BaseState, string[]>>;
    /** One-shot gesture clips */
    gestures: Record<string, string>;
    /** Bone node names for the procedural layer (breathing, look-at) */
    bones: { head: string; neck: string; spine: string[] };
}

export const AVATAR_MODELS: Record<string, AvatarModelManifest> = {
    // High-detail model authored in Blender (302k verts, desktop-only) with
    // contract-named clips keyframed for each intent.
    freya_v2: {
        url: "/models/FreyaV2.glb",
        scale: 1.0,
        yOffset: -0.95,
        base: {
            idle: ["Idle_Breathing"],
            listening: ["Listening"],
            attentive: ["Listening"],
            thinking: ["Thinking"],
            speaking: ["Talk_A", "Talk_B"],
            working: ["Thinking"],
            seated: ["Calm"],
            dance: ["Celebrate"],
        },
        gestures: {
            emphasize: "Emphasis",
            celebrate: "Celebrate",
            wave_off: "Alert",
            show_off: "Celebrate",
            admire: "Thinking",
            conjure: "Emphasis",
            groove: "Celebrate",
            transition_walk: "Emphasis",
            transition_run: "Alert",
            transition_flourish: "Celebrate",
        },
        bones: { head: "spine.006", neck: "spine.005", spine: ["spine.001", "spine.002", "spine.003"] },
    },
    freya: {
        url: "/models/Freya.glb",
        scale: 0.018,
        yOffset: -1.2,
        base: {
            idle: ["Idle_6"],
            listening: ["Idle_6"],
            attentive: ["Idle_6"],
            thinking: ["Mirror_Viewing"],
            speaking: [
                "Talk_Passionately",
                "Talk_with_Hands_Open",
                "Talk_with_Left_Hand_Raised",
                "Talk_with_Left_Hand_on_Hip",
            ],
            working: ["Magic_Genie"],
            seated: ["Chair_Sit_Idle_F"],
            dance: [
                "Denim_Pop_Dance",
                "Joyful_Dance_with_Hand_Sway",
                "Love_You_Pop_Dance",
                "Pod_Baby_Groove",
                "You_Groove",
                "Pop_Dance_LSA2",
            ],
        },
        gestures: {
            emphasize: "Talk_with_Left_Hand_Raised",
            celebrate: "Joyful_Dance_with_Hand_Sway",
            wave_off: "Dont_You_Dare",
            show_off: "Mirror_Viewing",
            admire: "Mirror_Viewing",
            conjure: "Magic_Genie",
            groove: "You_Groove",
            transition_walk: "Walking",
            transition_run: "Running",
            transition_flourish: "Magic_Genie",
        },
        bones: { head: "Head", neck: "neck", spine: ["Spine01", "Spine02"] },
    },
};

export const DEFAULT_AVATAR = "freya_v2";

// Expression → shader/UI accent hints (the GLB has no facial morph targets, so
// "expression" reads through posture bias + core glow + accent color).
export interface ExpressionAccent {
    glowBoost: number;
    speedBoost: number;
    ampBoost: number;
    breathScale: number;
    accent: string;
}

export const EXPRESSION_ACCENTS: Record<string, ExpressionAccent> = {
    joyful:  { glowBoost: 0.35, speedBoost: 0.3,  ampBoost: 0.08,  breathScale: 1.3, accent: "#ff8a75" },
    warm:    { glowBoost: 0.2,  speedBoost: 0.0,  ampBoost: 0.02,  breathScale: 1.1, accent: "#ffb3ac" },
    playful: { glowBoost: 0.3,  speedBoost: 0.45, ampBoost: 0.1,   breathScale: 1.35, accent: "#ff6f61" },
    focused: { glowBoost: 0.05, speedBoost: 0.25, ampBoost: -0.02, breathScale: 0.85, accent: "#e4beba" },
    stern:   { glowBoost: -0.1, speedBoost: 0.3,  ampBoost: -0.04, breathScale: 0.8,  accent: "#920703" },
    curious: { glowBoost: 0.15, speedBoost: 0.15, ampBoost: 0.05,  breathScale: 1.15, accent: "#ffdad6" },
    calm:    { glowBoost: -0.08, speedBoost: -0.15, ampBoost: -0.05, breathScale: 0.7, accent: "#c8c8b0" },
    alert:   { glowBoost: 0.4,  speedBoost: 0.6,  ampBoost: 0.06,  breathScale: 1.5, accent: "#d32f2f" },
};
