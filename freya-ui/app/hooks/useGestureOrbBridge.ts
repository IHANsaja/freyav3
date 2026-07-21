"use client";

import { useEffect, useRef } from "react";
import type { MutableRefObject } from "react";
import type { OrbFx } from "../components/scene/Orb";
import type { HandGestureState } from "./useHandGestures";

const POLL_MS = 160;
const COOLDOWN_MS = 1200;
const CONFIDENCE_FLOOR = 0.6;

/** Watches tracked hand gestures for confident, debounced transitions and
 *  dispatches "touch" reactions: an instant client-only shader pulse on the
 *  orb (OrbFx) plus a server round-trip so the live Gemini session reacts
 *  in character. This is the ONLY place that reads gestureRef.current.gesture
 *  — OrbCameraRig only reads .present/.x/.y — so continuous orbit tracking
 *  stays fully decoupled from discrete gesture reactions. */
export function useGestureOrbBridge(
  gestureRef: MutableRefObject<HandGestureState>,
  fxRef: MutableRefObject<OrbFx>,
  sendGestureTouch: (gesture: string) => void
) {
  const lastGesture = useRef<string | null>(null);
  const cooldownUntil = useRef(0);
  const sendRef = useRef(sendGestureTouch);
  sendRef.current = sendGestureTouch;

  useEffect(() => {
    const id = setInterval(() => {
      const hand = gestureRef.current;

      if (!hand.present || hand.gesture === "None" || hand.confidence < CONFIDENCE_FLOOR) {
        lastGesture.current = null;
        return;
      }

      if (hand.gesture === lastGesture.current) return;
      if (Date.now() < cooldownUntil.current) return;

      lastGesture.current = hand.gesture;
      cooldownUntil.current = Date.now() + COOLDOWN_MS;

      fxRef.current.touchBurst = 1;
      if (hand.gesture === "Closed_Fist") {
        fxRef.current.squeeze = 1;
      }
      sendRef.current(hand.gesture);
    }, POLL_MS);

    return () => clearInterval(id);
  }, [gestureRef, fxRef]);
}
