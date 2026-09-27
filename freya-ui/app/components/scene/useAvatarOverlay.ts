"use client";

import { useEffect, useState } from "react";
import type { AvatarIntent } from "../../hooks/useFreyaSocket";

export type OverlayState = "thinking" | "working";

interface Timed<T> {
  value: T;
  ms: number;
}

/** Avatar intents layered over the session state: a timed dance, a
 *  thinking/working overlay, and a timed expression name.
 *
 *  Each timed effect owns its own timer. Previously one effect keyed on the
 *  latest intent held the dance timer, so any other intent arriving mid-dance
 *  ran its cleanup, cleared the timer, and she kept dancing forever — the same
 *  happened to expression accents. */
export function useAvatarOverlay(state: string, intent: AvatarIntent | null | undefined) {
  const avatarIntent = intent ?? null;
  const [dance, setDance] = useState<Timed<AvatarIntent> | null>(null);
  const [expression, setExpression] = useState<Timed<{ name: string; intensity: number }> | null>(null);
  const [override, setOverride] = useState<OverlayState | null>(null);

  // Apply each new intent / state change while rendering (React's "adjusting
  // state when a prop changes" pattern) instead of in an effect.
  const [seenIntent, setSeenIntent] = useState<AvatarIntent | null>(null);
  if (avatarIntent !== seenIntent) {
    setSeenIntent(avatarIntent);
    if (avatarIntent?.intent === "state") {
      if (avatarIntent.name === "dance") {
        setDance({ value: avatarIntent, ms: avatarIntent.durationMs ?? 10000 });
      } else if (avatarIntent.name === "thinking" || avatarIntent.name === "working") {
        setOverride(avatarIntent.name);
      } else {
        setOverride(null);
      }
    } else if (avatarIntent?.intent === "expression") {
      setExpression({
        value: { name: avatarIntent.name, intensity: avatarIntent.intensity ?? 0.7 },
        ms: 12000,
      });
    }
  }

  // Speaking/interrupted always reclaim the avatar from thinking/working overlays.
  const [seenState, setSeenState] = useState(state);
  if (state !== seenState) {
    setSeenState(state);
    if (state === "speaking" || state === "interrupted") setOverride(null);
  }

  useEffect(() => {
    if (!dance) return;
    const timer = setTimeout(() => setDance(null), dance.ms);
    return () => clearTimeout(timer);
  }, [dance]);

  useEffect(() => {
    if (!expression) return;
    const timer = setTimeout(() => setExpression(null), expression.ms);
    return () => clearTimeout(timer);
  }, [expression]);

  return {
    dancing: dance !== null,
    override,
    expression: expression?.value ?? null,
  };
}
