"use client";

/** Capsule status readout under the orb viewport. Re-keys on text change so
 *  the swap animation replays. */
export default function StatusStrip({ text }: { text: string }) {
  return (
    <div
      role="status"
      aria-live="polite"
      className="flex items-center justify-center px-6 py-2.5 border rounded-full"
      style={{
        borderColor: "var(--panel-border)",
        background: "var(--panel-bg)",
        backdropFilter: "blur(var(--blur))",
      }}
    >
      <p
        key={text}
        className="text-[11px] font-mono tracking-[0.2em] uppercase text-center"
        style={{
          color: "var(--text-primary)",
          textShadow: "0 0 10px rgba(61,237,180,0.35)",
          animation: "strip-swap 0.4s ease-out",
        }}
      >
        {text}
      </p>
    </div>
  );
}
