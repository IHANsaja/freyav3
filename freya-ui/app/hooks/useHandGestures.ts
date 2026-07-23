"use client";

import { useEffect, useRef, useState } from "react";
import type { MutableRefObject } from "react";

export type GestureLabel =
  | "None"
  | "Closed_Fist"
  | "Open_Palm"
  | "Pointing_Up"
  | "Thumb_Down"
  | "Thumb_Up"
  | "Victory"
  | "ILoveYou";

export interface HandGestureState {
  present: boolean;
  /** Normalized [0,1], mirrored so it matches the on-screen (selfie) view. */
  x: number;
  /** Normalized [0,1]. */
  y: number;
  gesture: GestureLabel;
  confidence: number;
  /** How hard the hand is closed, 0 (flat open) → 1 (tight fist). Continuous
   *  and independent of the discrete `gesture` label, so the orb can be
   *  squeezed by degrees rather than only on a recognized Closed_Fist. */
  grip: number;
  /** Apparent palm length (wrist→middle knuckle) in normalized frame units —
   *  a proxy for how close the hand is to the camera. Unaffected by finger
   *  curl, so it stays independent of `grip`. */
  span: number;
  /** Thumb-tip → index-tip distance in palm-lengths: ~0.2 when the fingers are
   *  touching, ~2.5 with the hand wide open. Scale-invariant like `grip`, and
   *  measured from fingers that `grip` deliberately ignores, so pinching to
   *  zoom and clenching to squeeze can't be mistaken for one another. */
  pinch: number;
}

export type HandTrackingStatus = "idle" | "starting" | "active" | "denied" | "unsupported" | "error";

const IDLE_STATE: HandGestureState = {
  present: false, x: 0.5, y: 0.5, gesture: "None", confidence: 0, grip: 0, span: 0,
  pinch: 0,
};

const CONFIDENCE_FLOOR = 0.5;
const INFER_INTERVAL_MS = 66; // ~15fps — inference is far more expensive than the render loop
const PALM_LANDMARKS = [0, 5, 9, 13, 17]; // wrist + finger MCPs — stable centroid
const THUMB_TIP = 4;
const INDEX_TIP = 8;
// Middle, ring and pinky only. The index is deliberately left out: it pairs
// with the thumb to form the pinch that drives zoom, so counting it here would
// make every pinch read as a partial squeeze. Grip and pinch therefore measure
// disjoint sets of fingers and stay genuinely independent. The thumb is out for
// the original reason — it folds across the palm at wildly varying angles.
const GRIP_FINGERTIPS = [12, 16, 20];

// Curl ratio (mean fingertip→palm distance ÷ hand span) at the extremes. Tuned
// against a real webcam: a flat open hand sits near 2.0, a tight fist near 0.8.
const GRIP_OPEN = 1.95;
const GRIP_CLOSED = 0.85;

/** Centroid of wrist + finger knuckles — a stable stand-in for "where the hand
 *  is", far less jittery than any single landmark. */
function _palm(lm: { x: number; y: number }[]): { x: number; y: number } {
  let px = 0;
  let py = 0;
  for (const i of PALM_LANDMARKS) {
    px += lm[i].x;
    py += lm[i].y;
  }
  return { x: px / PALM_LANDMARKS.length, y: py / PALM_LANDMARKS.length };
}

/** The three continuous analog channels, measured so they don't collide.
 *
 *  `grip` (0 open → 1 tight fist): mean middle/ring/pinky-tip → palm-centre
 *  distance, divided by hand span. Dividing by span is what makes it work at
 *  any distance from the camera — both terms scale together, so a fist far
 *  away still reads as a fist.
 *
 *  `pinch`: thumb-tip → index-tip distance in those same span units. Uses the
 *  two fingers `grip` ignores, so a deliberate pinch (thumb and index together,
 *  other fingers extended) registers zoom without registering squeeze, and a
 *  fist registers squeeze while the caller's fist-guard suppresses zoom.
 *
 *  `span` is the raw wrist→middle-knuckle length. It measures the palm, not the
 *  fingers, so curling changes nothing — only distance from the camera does. */
function _metrics(
  lm: { x: number; y: number }[]
): { grip: number; span: number; pinch: number } {
  const wrist = lm[0];
  const midMcp = lm[9];
  const span = Math.hypot(midMcp.x - wrist.x, midMcp.y - wrist.y);
  if (span < 1e-4) return { grip: 0, span: 0, pinch: 0 }; // degenerate detection

  const { x: px, y: py } = _palm(lm);

  let reach = 0;
  for (const i of GRIP_FINGERTIPS) {
    reach += Math.hypot(lm[i].x - px, lm[i].y - py);
  }
  const ratio = reach / GRIP_FINGERTIPS.length / span;
  const t = (GRIP_OPEN - ratio) / (GRIP_OPEN - GRIP_CLOSED);

  const pinch =
    Math.hypot(lm[THUMB_TIP].x - lm[INDEX_TIP].x, lm[THUMB_TIP].y - lm[INDEX_TIP].y) / span;

  return { grip: Math.max(0, Math.min(1, t)), span, pinch };
}

/** MediaPipe's WASM writes ALL its diagnostics — including plain INFO lines — to
 *  stderr, which Emscripten maps onto console.error. Next.js's dev overlay then
 *  surfaces each one as a "Console Error", burying real errors under noise that
 *  is entirely expected (XNNPACK delegate selection, the non-square ROI notice,
 *  GL error-checking being off). Matched narrowly: the glog prefix + source-file
 *  form these emit, and the one XNNPACK INFO line. Anything else still gets
 *  through, so genuine MediaPipe failures remain visible. */
const MEDIAPIPE_NOISE =
  /(?:Created TensorFlow Lite XNNPACK delegate|^\s*[WIE]\d{4}\s[\d:.]+\s+\d+\s+\S+\.cc:\d+\])/;

function isMediaPipeNoise(args: unknown[]): boolean {
  const first = args[0];
  return typeof first === "string" && MEDIAPIPE_NOISE.test(first);
}

/** Temporarily swaps in a filtering console, returning a restore function.
 *
 *  This MUST wrap the *creation* of the MediaPipe module, not its later calls.
 *  The Emscripten glue in vision_wasm_internal.js does, once at instantiation:
 *
 *      var err = Module["printErr"] || console.error.bind(console);
 *
 *  — it captures a bound reference there and then. Patching console.error after
 *  the module exists therefore does nothing at all (the WASM keeps calling its
 *  own captured copy), which is why filtering at the call site failed.
 *
 *  Patching around creation instead gets both halves right: the WASM captures
 *  the filtering wrapper and keeps using it for the rest of the session, while
 *  the app's own console is handed straight back. Nothing else in the app ever
 *  runs through a patched console, so unrelated stack traces stay clean. */
function installMediaPipeLogFilter(): () => void {
  const original = { error: console.error, warn: console.warn, info: console.info };
  const wrap =
    (target: (...a: unknown[]) => void) =>
    (...args: unknown[]) => {
      if (!isMediaPipeNoise(args)) target(...args);
    };
  console.error = wrap(original.error);
  console.warn = wrap(original.warn);
  console.info = wrap(original.info);
  return () => {
    console.error = original.error;
    console.warn = original.warn;
    console.info = original.info;
  };
}

/** Tracks a single hand's position + recognized gesture from the user's webcam via
 *  MediaPipe's GestureRecognizer. Purely a sensor: exposes results through a mutable
 *  ref (no React state churn per frame), matching the fxRef/moodRef convention used
 *  elsewhere in the orb scene. Every failure path (no camera, permission denied,
 *  model load failure) degrades to an idle ref rather than throwing — callers never
 *  need to special-case errors, just read `status` for an optional UI indicator. */
/** @param deviceId Optional specific camera to use (from useVideoDevices). Falls
 *  back to the system default front-facing camera when omitted. */
export function useHandGestures(enabled: boolean, deviceId?: string): {
  stateRef: MutableRefObject<HandGestureState>;
  status: HandTrackingStatus;
} {
  const stateRef = useRef<HandGestureState>({ ...IDLE_STATE });
  const [status, setStatus] = useState<HandTrackingStatus>("idle");

  useEffect(() => {
    if (!enabled) {
      stateRef.current = { ...IDLE_STATE };
      setStatus("idle");
      return;
    }

    if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia) {
      setStatus("unsupported");
      return;
    }

    let cancelled = false;
    let stream: MediaStream | null = null;
    let video: HTMLVideoElement | null = null;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let recognizer: any = null;
    let rafId = 0;
    let lastInferAt = 0;

    setStatus("starting");

    (async () => {
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: deviceId
            ? { deviceId: { exact: deviceId }, width: { ideal: 320 }, height: { ideal: 240 } }
            : { facingMode: "user", width: { ideal: 320 }, height: { ideal: 240 } },
        });
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }

        video = document.createElement("video");
        video.muted = true;
        video.playsInline = true;
        video.srcObject = stream;
        await video.play();

        const { FilesetResolver, GestureRecognizer } = await import("@mediapipe/tasks-vision");
        if (cancelled) return;

        // The filter has to be in place while the WASM module is instantiated —
        // that's the one moment it captures its stderr sink. Restored in
        // `finally`, after which the app's console is untouched for good.
        const restoreConsole = installMediaPipeLogFilter();
        try {
          const vision = await FilesetResolver.forVisionTasks("/mediapipe/wasm");
          if (cancelled) return;

          try {
            recognizer = await GestureRecognizer.createFromOptions(vision, {
              baseOptions: { modelAssetPath: "/mediapipe/models/gesture_recognizer.task", delegate: "GPU" },
              runningMode: "VIDEO",
              numHands: 1,
            });
          } catch {
            recognizer = await GestureRecognizer.createFromOptions(vision, {
              baseOptions: { modelAssetPath: "/mediapipe/models/gesture_recognizer.task", delegate: "CPU" },
              runningMode: "VIDEO",
              numHands: 1,
            });
          }
        } finally {
          restoreConsole();
        }
        if (cancelled) {
          recognizer.close();
          return;
        }

        setStatus("active");

        const loop = (now: number) => {
          if (cancelled) return;
          rafId = requestAnimationFrame(loop);

          if (document.hidden) return;
          if (now - lastInferAt < INFER_INTERVAL_MS) return;
          lastInferAt = now;
          if (!video || video.readyState < 2) return;

          // No console wrapping here: the WASM captured its stderr sink at
          // instantiation, so per-frame logs already route through the filter
          // installed back then.
          const result = recognizer.recognizeForVideo(video, now);
          const allHands: { x: number; y: number }[][] = result.landmarks ?? [];
          const primary = allHands[0];
          const topGesture = result.gestures?.[0]?.[0];

          if (!primary || !topGesture) {
            stateRef.current = { ...IDLE_STATE };
            return;
          }

          const palm = _palm(primary);
          const confidence = topGesture.score ?? 0;
          const gesture = (confidence >= CONFIDENCE_FLOOR ? topGesture.categoryName : "None") as GestureLabel;
          const { grip, span, pinch } = _metrics(primary);

          stateRef.current = {
            present: true,
            x: 1 - palm.x, // mirror for selfie-view intuition
            y: palm.y,
            gesture,
            confidence,
            grip,
            span,
            pinch,
          };
        };
        rafId = requestAnimationFrame(loop);
      } catch (err) {
        if (cancelled) return;
        const name = (err as { name?: string })?.name;
        setStatus(name === "NotAllowedError" || name === "SecurityError" ? "denied" : "error");
        stateRef.current = { ...IDLE_STATE };
      }
    })();

    return () => {
      cancelled = true;
      if (rafId) cancelAnimationFrame(rafId);
      stream?.getTracks().forEach((t) => t.stop());
      recognizer?.close?.();
      stateRef.current = { ...IDLE_STATE };
    };
  }, [enabled, deviceId]);

  return { stateRef, status };
}
