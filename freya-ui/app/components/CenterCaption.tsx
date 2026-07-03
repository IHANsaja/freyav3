"use client";

import { useEffect, useRef } from "react";
import Typewriter from "./Typewriter";
import { FreyaState } from "../hooks/useFreyaSocket";

/**
 * Freya's words, shown as a bounded subtitle bar above the control dock — never as a
 * growing box over the avatar. A fixed max-height + top fade keeps long replies from
 * creeping upward into her face; the inner pane auto-scrolls so the newest words stay
 * in view as she talks, like live captions.
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
  const paneRef = useRef<HTMLDivElement>(null);

  // Keep the latest line in view as the typewriter reveals more text.
  useEffect(() => {
    const el = paneRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [liveText]);

  return (
    <div className="absolute inset-x-0 bottom-56 flex justify-center px-6 pointer-events-none z-20">
      <div
        className={`w-full max-w-xl text-center transition-all duration-500 ${
          speaking ? "opacity-100 translate-y-0" : "opacity-0 translate-y-2"
        }`}
      >
        <div
          className="px-6 py-3 rounded-2xl"
          style={{
            background:
              "linear-gradient(180deg, rgba(10,8,8,0.75) 0%, rgba(15,10,10,0.6) 100%)",
            backdropFilter: "blur(10px)",
            WebkitBackdropFilter: "blur(10px)",
            maskImage: "linear-gradient(180deg, transparent 0%, black 24px)",
            WebkitMaskImage: "linear-gradient(180deg, transparent 0%, black 24px)",
          }}
        >
          <div ref={paneRef} className="max-h-[6.5rem] overflow-y-auto scroll-smooth">
            <Typewriter
              text={liveText}
              className="text-[1.05rem] leading-relaxed font-medium tracking-wide text-parchment"
              charsPerTick={2}
              tickMs={16}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
