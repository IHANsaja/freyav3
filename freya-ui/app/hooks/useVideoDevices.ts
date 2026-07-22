"use client";

import { useCallback, useEffect, useState } from "react";

export interface VideoDevice {
  deviceId: string;
  label: string;
}

/** Enumerates the browser's video input devices for the camera-select
 *  dropdown next to the hand-tracking toggle. Device labels are only
 *  populated by the browser once camera permission has been granted at
 *  least once in this origin — before that, entries still have a usable
 *  deviceId but a blank label, so we fall back to a numbered placeholder. */
export function useVideoDevices(): VideoDevice[] {
  const [devices, setDevices] = useState<VideoDevice[]>([]);

  const refresh = useCallback(() => {
    if (typeof navigator === "undefined" || !navigator.mediaDevices?.enumerateDevices) return;
    navigator.mediaDevices
      .enumerateDevices()
      .then((list) => {
        const cams = list
          .filter((d) => d.kind === "videoinput")
          .map((d, i) => ({ deviceId: d.deviceId, label: d.label || `Camera ${i + 1}` }));
        setDevices(cams);
      })
      .catch(() => setDevices([]));
  }, []);

  useEffect(() => {
    refresh();
    if (typeof navigator === "undefined" || !navigator.mediaDevices) return;
    navigator.mediaDevices.addEventListener("devicechange", refresh);
    return () => navigator.mediaDevices.removeEventListener("devicechange", refresh);
  }, [refresh]);

  return devices;
}
