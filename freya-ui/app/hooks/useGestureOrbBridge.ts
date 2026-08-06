"use client";

import { useEffect, useRef } from "react";
import type { MutableRefObject } from "react";
import type { OrbFx } from "../components/scene/Orb";
import type { GestureLabel, HandGestureState } from "./useHandGestures";

const POLL_MS = 160;
const COOLDOWN_MS = 1200;
const CONFIDENCE_FLOOR = 0.6;

/** Poses that count as a deliberate signal to Freya: a squeeze, or an
 *  intentional hand sign.
 *
 *  `Open_Palm` is deliberately EXCLUDED. It's the pose a relaxed hand falls
 *  into while moving around to spin the orb, so treating it as a gesture made
 *  Freya react to what was really just steering. Dragging is now silent — she
 *  only speaks up when the user actually signs at her or squeezes. */
const REACTIVE_GESTURES: ReadonlySet<GestureLabel> = new Set<GestureLabel>([
  "Closed_Fist",
  "Victory",
  "Thumb_Up",
  "Thumb_Down",
  "Pointing_Up",
  "ILoveYou",
]);

/** Watches tracked hand gestures for confident, debounced transitions and
 *  dispatches reactions: an instant client-only shader pulse on the orb
 *  (OrbFx) plus a server round-trip so the live Gemini session reacts in
 *  character. This is the ONLY place that reads gestureRef.current.gesture —
 *  Orb.tsx's hand-drag reads only .present/.x/.y — so spinning the orb stays
 *  fully decoupled from, and silent compared to, discrete gesture reactions. */
export function useGestureOrbBridge(
  gestureRef: MutableRefObject<HandGestureState>,
  fxRef: MutableRefObject<OrbFx>,
  sendGestureTouch: (gesture: string) => void
) {
  const lastGesture = useRef<string | null>(null);
  const cooldownUntil = useRef(0);
  // Kept in a ref so the polling effect never has to re-subscribe when the
  // callback identity changes. Updated in an effect rather than during render —
  // mutating a ref mid-render is a React correctness violation.
  const sendRef = useRef(sendGestureTouch);
  useEffect(() => {
    sendRef.current = sendGestureTouch;
  }, [sendGestureTouch]);

  useEffect(() => {
    const id = setInterval(() => {
      const hand = gestureRef.current;

      // Anything that isn't a deliberate sign — no hand, an unclassified pose,
      // a low-confidence read, or the open palm used for dragging — clears the
      // edge-trigger memory so the NEXT real sign still fires.
      if (
        !hand.present ||
        hand.confidence < CONFIDENCE_FLOOR ||
        !REACTIVE_GESTURES.has(hand.gesture)
      ) {
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
