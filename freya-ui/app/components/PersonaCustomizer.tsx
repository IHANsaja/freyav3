"use client";

import { useCallback, useEffect, useRef, useState } from "react";

const API = "http://localhost:8000";

type TraitKey = "warmth" | "humor" | "detail" | "initiative";
type Traits = Record<TraitKey, number>;

interface StyleInfo {
  label: string;
  model: string;
  model_label: string;
  summary: string;
  traits: Traits;
}

interface PersonaData {
  setup_done: boolean;
  style: string;
  traits: Traits;
  accent: string;
  note: string;
  name: string;
  voice: string;
  voices: string[];
  styles: Record<string, StyleInfo>;
  accents: string[];
}

const TRAIT_ORDER: { key: TraitKey; label: string; low: string; high: string }[] = [
  { key: "warmth", label: "Warmth", low: "Matter-of-fact", high: "Warm & caring" },
  { key: "humor", label: "Humour", low: "Serious", high: "Playful" },
  { key: "detail", label: "Detail", low: "Brief", high: "Thorough" },
  { key: "initiative", label: "Initiative", low: "Waits for you", high: "Proactive" },
];

const STYLE_ICON: Record<string, string> = { friendly: "✦", quick: "⚡", focused: "◎" };

const STEPS = ["Style", "Personality", "Voice & look", "About you"];

/** Roughly how she'd open a conversation at these settings - a feel for the sliders. */
function previewLine(traits: Traits, name: string) {
  const who = name.trim() || "there";
  const hello =
    traits.warmth > 66 ? `Hey ${who}! So good to see you.` : traits.warmth > 33 ? `Hi ${who}.` : `Hello, ${who}.`;
  const joke =
    traits.humor > 66 ? " Ready to cause some trouble?" : traits.humor > 33 ? " What are we up to today?" : "";
  const offer =
    traits.initiative > 66
      ? " Your project is still open - want me to pick up where we left off?"
      : traits.initiative > 33
        ? " What can I help with?"
        : " Tell me what you need.";
  const detail = traits.detail > 66 ? " I can walk you through it step by step." : "";
  return hello + joke + offer + detail;
}

interface PersonaCustomizerProps {
  isOpen: boolean;
  connected: boolean;
  /** Called when the backend reports the customizer has never been completed. */
  onRequestOpen: () => void;
  onClose: () => void;
  /** After a successful save: the model and voice in the dashboard config changed. */
  onSaved: () => void;
}

export default function PersonaCustomizer({
  isOpen,
  connected,
  onRequestOpen,
  onClose,
  onSaved,
}: PersonaCustomizerProps) {
  const [data, setData] = useState<PersonaData | null>(null);
  const [draft, setDraft] = useState<PersonaData | null>(null);
  const [step, setStep] = useState(0);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  // First-run setup is offered once per page at most: the load below re-runs
  // on every socket reconnect, which used to pop the dialog up mid-session.
  const offered = useRef(false);

  const load = useCallback(() => {
    fetch(`${API}/persona`)
      .then((r) => r.json())
      .then((res: PersonaData) => {
        setData(res);
        setDraft(res);
        if (!res.setup_done && !offered.current) {
          offered.current = true;
          onRequestOpen();
        }
      })
      .catch(() => {
        // Backend offline: the customizer simply isn't offered until it's back.
      });
  }, [onRequestOpen]);

  // (Re)load whenever the backend connects, so first-run detection works even
  // when server.py starts after the page.
  useEffect(() => {
    if (connected) load();
  }, [connected, load]);

  // Opening starts from the saved values on the first step.
  const [openedFor, setOpenedFor] = useState(false);
  if (openedFor !== isOpen) {
    setOpenedFor(isOpen);
    if (isOpen) {
      setDraft(data);
      setStep(0);
      setError("");
    }
  }

  if (!isOpen || !draft) return null;

  const style = draft.styles[draft.style];
  const last = step === STEPS.length - 1;

  const pickStyle = (id: string) =>
    // A new style resets the sliders to that style's starting point.
    setDraft({ ...draft, style: id, traits: { ...draft.styles[id].traits } });

  // Closing the first-run dialog without saving still counts as "offered":
  // record it so it never reappears on the next load. Defaults stay as they are.
  const dismiss = () => {
    if (data && !data.setup_done) {
      setData({ ...data, setup_done: true });
      fetch(`${API}/persona/dismiss`, { method: "POST" }).catch(() => {
        // Backend offline: it may be offered once more next time, nothing worse.
      });
    }
    onClose();
  };

  const save = async (values: PersonaData) => {
    setSaving(true);
    setError("");
    try {
      const res = await fetch(`${API}/persona`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          style: values.style,
          traits: values.traits,
          accent: values.accent,
          note: values.note,
          name: values.name,
          voice: values.voice,
        }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok || body.error) throw new Error(body.message || "Could not save - is Freya's server running?");
      setData({ ...values, setup_done: true });
      onSaved();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const accentVars = {
    "--pc-accent": draft.accent,
    "--pc-accent-soft": `${draft.accent}33`,
  } as React.CSSProperties;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-surface-container-lowest/80 backdrop-blur-sm p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="persona-title"
    >
      <div
        className="w-full max-w-[860px] max-h-[92vh] flex flex-col bg-surface-container-low border"
        style={{ ...accentVars, borderColor: "var(--pc-accent)", transition: "border-color 0.4s ease" }}
      >
        {/* Header + step indicator */}
        <div className="shrink-0 px-6 pt-5 pb-4 border-b border-outline-variant/30">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2
                id="persona-title"
                className="text-sm font-bold tracking-[0.2em] uppercase"
                style={{ color: "var(--pc-accent)", fontFamily: "var(--font-display)" }}
              >
                {data?.setup_done ? "Customize Freyja" : "Meet Freyja"}
              </h2>
              <p className="text-xs text-on-surface-variant mt-1">
                {data?.setup_done
                  ? "Tune how she talks and works. Changes apply as soon as you save."
                  : "Choose how she should be before your first conversation. You can change this any time."}
              </p>
            </div>
            <button
              onClick={dismiss}
              aria-label="Close customizer"
              className="text-on-surface-variant hover:text-parchment text-lg font-light transition-colors"
            >
              ✕
            </button>
          </div>
          <ol className="flex gap-2 mt-4" aria-label="Steps">
            {STEPS.map((label, i) => (
              <li key={label} className="flex-1 min-w-0">
                <button
                  onClick={() => setStep(i)}
                  className="w-full text-left"
                  aria-current={i === step ? "step" : undefined}
                >
                  <span
                    className="block h-1 rounded-full transition-colors duration-300"
                    style={{ background: i <= step ? "var(--pc-accent)" : "var(--panel-border)" }}
                  />
                  <span
                    className="block mt-1.5 text-[10px] tracking-wider uppercase truncate"
                    style={{ color: i === step ? "var(--text-primary)" : "var(--text-secondary)" }}
                  >
                    {i + 1}. {label}
                  </span>
                </button>
              </li>
            ))}
          </ol>
        </div>

        {/* Body */}
        <div className="flex-1 min-h-0 overflow-y-auto p-6">
          {step === 0 && (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              {Object.entries(draft.styles).map(([id, s]) => {
                const active = id === draft.style;
                return (
                  <button
                    key={id}
                    onClick={() => pickStyle(id)}
                    aria-pressed={active}
                    className="text-left p-4 border transition-all duration-200 flex flex-col gap-2"
                    style={{
                      borderRadius: "var(--radius)",
                      borderColor: active ? "var(--pc-accent)" : "var(--panel-border)",
                      background: active ? "var(--pc-accent-soft)" : "transparent",
                      boxShadow: active ? "0 0 18px var(--pc-accent-soft)" : "none",
                    }}
                  >
                    <span className="text-xl" style={{ color: "var(--pc-accent)" }} aria-hidden>
                      {STYLE_ICON[id] ?? "•"}
                    </span>
                    <span className="text-sm font-bold tracking-wider uppercase text-parchment">{s.label}</span>
                    <span className="text-[10px] font-mono tracking-wider uppercase text-on-surface-variant">
                      {s.model_label}
                    </span>
                    <span className="text-xs text-on-surface-variant leading-relaxed">{s.summary}</span>
                  </button>
                );
              })}
            </div>
          )}

          {step === 1 && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6 items-start">
              <div className="flex flex-col gap-5">
                {TRAIT_ORDER.map(({ key, label, low, high }) => (
                  <label key={key} className="flex flex-col gap-2">
                    <span className="flex justify-between text-[11px] font-bold uppercase tracking-wider text-outline">
                      <span>{label}</span>
                      <span style={{ color: "var(--pc-accent)" }}>{draft.traits[key]}</span>
                    </span>
                    <input
                      type="range"
                      min={0}
                      max={100}
                      step={5}
                      value={draft.traits[key]}
                      onChange={(e) =>
                        setDraft({ ...draft, traits: { ...draft.traits, [key]: Number(e.target.value) } })
                      }
                      className="w-full"
                      style={{ accentColor: draft.accent }}
                    />
                    <span className="flex justify-between text-[10px] text-on-surface-variant">
                      <span>{low}</span>
                      <span>{high}</span>
                    </span>
                  </label>
                ))}
              </div>
              <div
                className="p-4 border flex flex-col gap-3"
                style={{ borderRadius: "var(--radius)", borderColor: "var(--panel-border)" }}
              >
                <span className="text-[10px] uppercase tracking-wider text-on-surface-variant">
                  Preview - roughly how she&apos;ll greet you
                </span>
                <p className="text-sm leading-relaxed text-parchment" aria-live="polite">
                  &ldquo;{previewLine(draft.traits, draft.name)}&rdquo;
                </p>
                <button
                  onClick={() => setDraft({ ...draft, traits: { ...style.traits } })}
                  className="self-start text-[10px] uppercase tracking-wider text-on-surface-variant hover:text-parchment underline underline-offset-4"
                >
                  Reset to {style.label} defaults
                </button>
              </div>
            </div>
          )}

          {step === 2 && (
            <div className="flex flex-col gap-6">
              <div className="flex flex-col gap-2">
                <span className="text-[11px] font-bold uppercase tracking-wider text-outline">Voice</span>
                <div className="flex flex-wrap gap-3">
                  {draft.voices.map((v) => {
                    const active = v === draft.voice;
                    return (
                      <button
                        key={v}
                        onClick={() => setDraft({ ...draft, voice: v })}
                        aria-pressed={active}
                        className="px-6 py-2 rounded-full text-xs font-semibold tracking-wider border transition-all duration-200"
                        style={{
                          borderColor: active ? "var(--pc-accent)" : "var(--panel-border)",
                          background: active ? "var(--pc-accent)" : "transparent",
                          color: active ? "#07050a" : "var(--text-secondary)",
                        }}
                      >
                        {v}
                      </button>
                    );
                  })}
                </div>
              </div>
              <div className="flex flex-col gap-2">
                <span className="text-[11px] font-bold uppercase tracking-wider text-outline">Accent colour</span>
                <div className="flex flex-wrap gap-3">
                  {draft.accents.map((c) => {
                    const active = c.toLowerCase() === draft.accent.toLowerCase();
                    return (
                      <button
                        key={c}
                        onClick={() => setDraft({ ...draft, accent: c })}
                        aria-label={`Accent colour ${c}`}
                        aria-pressed={active}
                        className="w-10 h-10 rounded-full transition-transform duration-200 hover:scale-110"
                        style={{
                          background: c,
                          outline: active ? "2px solid var(--text-primary)" : "none",
                          outlineOffset: "3px",
                          boxShadow: `0 0 14px ${c}66`,
                        }}
                      />
                    );
                  })}
                </div>
                <p className="text-[10px] text-on-surface-variant">
                  Used for her everyday look. Other modes keep their own colours.
                </p>
              </div>
            </div>
          )}

          {step === 3 && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6 items-start">
              <div className="flex flex-col gap-5">
                <label className="flex flex-col gap-2">
                  <span className="text-[11px] font-bold uppercase tracking-wider text-outline">
                    What should she call you?
                  </span>
                  <input
                    value={draft.name}
                    maxLength={40}
                    onChange={(e) => setDraft({ ...draft, name: e.target.value.replace(/[\r\n#]/g, "") })}
                    placeholder="Your name"
                    className="bg-surface-container-lowest border border-outline-variant/40 text-on-surface text-sm px-4 py-3 focus:outline-none"
                    style={{ borderRadius: "0px" }}
                  />
                </label>
                <label className="flex flex-col gap-2">
                  <span className="text-[11px] font-bold uppercase tracking-wider text-outline">
                    Anything else she should know? <span className="font-normal normal-case">(optional)</span>
                  </span>
                  <textarea
                    value={draft.note}
                    maxLength={400}
                    rows={4}
                    onChange={(e) => setDraft({ ...draft, note: e.target.value })}
                    placeholder="e.g. I'm learning Python - explain code simply. Don't use slang."
                    className="bg-surface-container-lowest border border-outline-variant/40 text-on-surface text-sm px-4 py-3 focus:outline-none resize-none"
                    style={{ borderRadius: "0px" }}
                  />
                  <span className="text-[10px] text-on-surface-variant text-right">{draft.note.length}/400</span>
                </label>
              </div>
              <div
                className="p-4 border flex flex-col gap-2 text-xs"
                style={{ borderRadius: "var(--radius)", borderColor: "var(--panel-border)" }}
              >
                <span className="text-[10px] uppercase tracking-wider text-on-surface-variant">Summary</span>
                <span className="text-parchment">
                  <b style={{ color: "var(--pc-accent)" }}>{style.label}</b> - {style.model_label}
                </span>
                <span className="text-on-surface-variant">Voice: {draft.voice}</span>
                <span className="text-on-surface-variant">
                  {TRAIT_ORDER.map(({ key, label }) => `${label} ${draft.traits[key]}`).join(" · ")}
                </span>
                <p className="text-parchment mt-2 leading-relaxed">&ldquo;{previewLine(draft.traits, draft.name)}&rdquo;</p>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="shrink-0 flex flex-wrap items-center justify-between gap-3 px-6 py-4 border-t border-outline-variant/30">
          <div className="text-xs min-h-[1rem]" role="alert" style={{ color: "var(--accent-red-dim, #e0559a)" }}>
            {error}
          </div>
          <div className="flex items-center gap-3 ml-auto">
            {!data?.setup_done && step === 0 && (
              <button
                onClick={() => save(draft)}
                disabled={saving}
                className="text-[11px] uppercase tracking-wider text-on-surface-variant hover:text-parchment px-3 py-2"
              >
                Use defaults
              </button>
            )}
            {step > 0 && (
              <button
                onClick={() => setStep(step - 1)}
                className="text-[11px] uppercase tracking-wider text-on-surface-variant hover:text-parchment px-3 py-2"
              >
                Back
              </button>
            )}
            <button
              onClick={() => (last ? save(draft) : setStep(step + 1))}
              disabled={saving}
              className="px-6 py-2.5 rounded-full text-xs font-bold tracking-wider uppercase transition-all duration-200 disabled:opacity-50"
              style={{ background: "var(--pc-accent)", color: "#07050a" }}
            >
              {last ? (saving ? "Saving..." : data?.setup_done ? "Save changes" : "Meet Freyja") : "Next"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
