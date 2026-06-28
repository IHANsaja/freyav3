"use client";

import Typewriter from "./Typewriter";
import { FreyaState } from "../hooks/useFreyaSocket";

/**
 * Freya's words, typed out live on a layer ABOVE the 3D scene canvas, centered — as if she's
 * speaking them into the scene. Fades in while she talks, fades out when she stops.
 */
export default function CenterCaption({
  state,
  liveText,
}: {
  state: FreyaState;
  liveText: string;
}) {
  // Visible whenever there are live words to show — robust to state-event timing.
  void state;
  const speaking = liveText.trim().length > 0;

  return (
    <div className="absolute inset-x-0 top-[36%] -translate-y-1/2 flex justify-center px-6 pointer-events-none z-20">
      <div
        className={`max-w-3xl text-center transition-all duration-500 ${
          speaking ? "opacity-100 translate-y-0" : "opacity-0 translate-y-2"
        }`}
      >
        <div
          className="inline-block px-8 py-5 rounded-3xl"
          style={{
            background:
              "radial-gradient(120% 120% at 50% 0%, rgba(20,10,10,0.55) 0%, rgba(10,8,8,0.25) 70%, transparent 100%)",
            backdropFilter: "blur(6px)",
            WebkitBackdropFilter: "blur(6px)",
          }}
        >
          <Typewriter
            text={liveText}
            className="text-[1.7rem] leading-relaxed font-medium tracking-wide text-parchment"
            charsPerTick={2}
            tickMs={16}
          />
        </div>
      </div>
    </div>
  );
}
