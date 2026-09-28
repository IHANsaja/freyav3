"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { RootState } from "@react-three/fiber";

/**
 * Recovery protocol for a <Canvas>: survive a lost WebGL context.
 *
 * Browsers drop GPU contexts on driver resets, sleep/resume, too many live
 * contexts, or a GPU process crash. three.js stops rendering and the scene
 * stays frozen (or blank) until a reload. Here the loss is caught
 * (preventDefault tells the browser we intend to restore), and the Canvas is
 * remounted with a fresh context — immediately on `webglcontextrestored`, or
 * after a short wait if the browser never sends it.
 *
 * Usage: `<Canvas key={canvasKey} onCreated={onCreated} …>`
 */
export function useWebGLRecovery(onCreatedExtra?: (state: RootState) => void) {
  const [canvasKey, setCanvasKey] = useState(0);
  const cleanup = useRef<(() => void) | null>(null);
  const extra = useRef(onCreatedExtra);
  useEffect(() => {
    extra.current = onCreatedExtra;
  }, [onCreatedExtra]);

  const onCreated = useCallback((state: RootState) => {
    cleanup.current?.();
    const canvas = state.gl.domElement;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const remount = () => {
      if (timer) clearTimeout(timer);
      timer = null;
      setCanvasKey((k) => k + 1);
    };
    const onLost = (e: Event) => {
      e.preventDefault();
      console.warn("[webgl] context lost — rebuilding the scene");
      // Some browsers never fire `restored`; don't wait on it forever.
      timer = setTimeout(remount, 1500);
    };
    canvas.addEventListener("webglcontextlost", onLost);
    canvas.addEventListener("webglcontextrestored", remount);
    cleanup.current = () => {
      if (timer) clearTimeout(timer);
      canvas.removeEventListener("webglcontextlost", onLost);
      canvas.removeEventListener("webglcontextrestored", remount);
    };
    extra.current?.(state);
  }, []);

  useEffect(() => () => cleanup.current?.(), []);

  return { canvasKey, onCreated };
}
