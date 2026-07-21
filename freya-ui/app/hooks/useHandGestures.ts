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
}

export type HandTrackingStatus = "idle" | "starting" | "active" | "denied" | "unsupported" | "error";

const IDLE_STATE: HandGestureState = { present: false, x: 0.5, y: 0.5, gesture: "None", confidence: 0 };

const CONFIDENCE_FLOOR = 0.5;
const INFER_INTERVAL_MS = 66; // ~15fps — inference is far more expensive than the render loop
const PALM_LANDMARKS = [0, 5, 9, 13, 17]; // wrist + finger MCPs — stable centroid

/** Tracks a single hand's position + recognized gesture from the user's webcam via
 *  MediaPipe's GestureRecognizer. Purely a sensor: exposes results through a mutable
 *  ref (no React state churn per frame), matching the fxRef/moodRef convention used
 *  elsewhere in the orb scene. Every failure path (no camera, permission denied,
 *  model load failure) degrades to an idle ref rather than throwing — callers never
 *  need to special-case errors, just read `status` for an optional UI indicator. */
export function useHandGestures(enabled: boolean): {
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
          video: { facingMode: "user", width: { ideal: 320 }, height: { ideal: 240 } },
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

          const result = recognizer.recognizeForVideo(video, now);
          const landmarks = result.landmarks?.[0];
          const topGesture = result.gestures?.[0]?.[0];

          if (!landmarks || !topGesture) {
            stateRef.current = { ...IDLE_STATE };
            return;
          }

          let sx = 0;
          let sy = 0;
          for (const i of PALM_LANDMARKS) {
            sx += landmarks[i].x;
            sy += landmarks[i].y;
          }
          const avgX = sx / PALM_LANDMARKS.length;
          const avgY = sy / PALM_LANDMARKS.length;

          const confidence = topGesture.score ?? 0;
          const gesture = (confidence >= CONFIDENCE_FLOOR ? topGesture.categoryName : "None") as GestureLabel;

          stateRef.current = {
            present: true,
            x: 1 - avgX, // mirror for selfie-view intuition
            y: avgY,
            gesture,
            confidence,
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
  }, [enabled]);

  return { stateRef, status };
}
