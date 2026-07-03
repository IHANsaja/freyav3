"use client";

import { useEffect, useState } from "react";

function format(totalSeconds: number): string {
  const h = Math.floor(totalSeconds / 3600) % 100;
  const m = Math.floor((totalSeconds % 3600) / 60);
  const s = totalSeconds % 60;
  return [h, m, s].map((n) => String(n).padStart(2, "0")).join(":");
}

/** Live HH:MM:SS session uptime, ticking every second from mount.
 *  Seeded so the console reads like it's been running a while. */
export function useUptime(seedSeconds = 2 * 3600 + 17 * 60 + 42): string {
  const [elapsed, setElapsed] = useState(seedSeconds);

  useEffect(() => {
    const id = setInterval(() => setElapsed((e) => e + 1), 1000);
    return () => clearInterval(id);
  }, []);

  return format(elapsed);
}
