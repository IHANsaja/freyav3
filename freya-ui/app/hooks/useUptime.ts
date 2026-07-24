"use client";

import { useSyncExternalStore } from "react";

function format(totalSeconds: number): string {
  const h = Math.floor(totalSeconds / 3600) % 100;
  const m = Math.floor((totalSeconds % 3600) / 60);
  const s = totalSeconds % 60;
  return [h, m, s].map((n) => String(n).padStart(2, "0")).join(":");
}

// ── The wall clock, as an external store ─────────────────────────────────
// The current second is genuinely external mutable state, so it is consumed
// through useSyncExternalStore rather than a setState-on-an-interval. That
// keeps render pure (no Date.now() while rendering) without needing to seed
// state synchronously inside an effect.
//
// The snapshot is cached per second: getSnapshot must return a stable value
// between ticks or React re-renders in a loop.
let cachedSecond = 0;

function subscribe(onChange: () => void): () => void {
  const id = setInterval(onChange, 1000);
  return () => clearInterval(id);
}

function getSnapshot(): number {
  const now = Math.floor(Date.now() / 1000);
  if (now !== cachedSecond) cachedSecond = now;
  return cachedSecond;
}

// Server render has no clock; uptime resolves on hydration.
const getServerSnapshot = (): number => 0;

/**
 * Live HH:MM:SS uptime for the *real* voice session.
 *
 * This used to seed itself with a couple of fabricated hours so the console
 * "read like it had been running a while", and counted from page load — so it
 * reported the browser tab's age rather than the session's. It now derives
 * from the backend's actual session start (`/status` → `startedAt`, unix
 * seconds) and returns null when nothing is running, so the UI can say so
 * honestly instead of inventing a number.
 */
export function useUptime(startedAt: number | null | undefined): string | null {
  const nowSeconds = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  if (!startedAt || !nowSeconds) return null;
  return format(Math.max(0, nowSeconds - startedAt));
}
