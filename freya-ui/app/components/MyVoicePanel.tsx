"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { AudioDevice } from "../hooks/useFreyaSocket";

const API = "http://localhost:8000/voice";

interface ChecklistItem {
  id: string;
  ok: boolean | null; // null = a manual step Freya can't check
  label: string;
  hint: string;
}

interface VoiceLogEntry {
  ts: string;
  tool: string;
  ok?: boolean;
  where?: string;
  app?: string | null;
  lines?: { text: string; cloned: boolean }[];
}

interface VoiceStatus {
  enabled: boolean;
  enrolled: boolean;
  voicebox: { ok: boolean; url: string; engines: string[]; engine: string | null };
  cable: { present: boolean; name: string | null; index: number | null };
  passthrough: { running: boolean; muted: boolean; ducked: boolean; error: string | null };
  call: { active: boolean; app: string | null };
  confirm: string;
  checklist: ChecklistItem[];
  log: VoiceLogEntry[];
}

interface Challenge {
  nonce: string;
  script: string;
  min_seconds: number;
  max_seconds: number;
}

const CONFIRM_LABELS: Record<string, string> = {
  first_per_call: "First line of each call",
  every_line: "Every line",
  off_after_answer: "Only when answering",
};

// Collects mono float samples from the mic; posts each block to the page.
const RECORDER_WORKLET = `
class Capture extends AudioWorkletProcessor {
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (ch) this.port.postMessage(ch.slice(0));
    return true;
  }
}
registerProcessor("freya-capture", Capture);
`;

/** 16-bit mono PCM WAV from float samples. */
function encodeWav(chunks: Float32Array[], rate: number): Blob {
  const length = chunks.reduce((n, c) => n + c.length, 0);
  const buffer = new ArrayBuffer(44 + length * 2);
  const view = new DataView(buffer);
  const text = (offset: number, s: string) => [...s].forEach((c, i) => view.setUint8(offset + i, c.charCodeAt(0)));
  text(0, "RIFF");
  view.setUint32(4, 36 + length * 2, true);
  text(8, "WAVE");
  text(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, rate, true);
  view.setUint32(28, rate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  text(36, "data");
  view.setUint32(40, length * 2, true);
  let offset = 44;
  for (const chunk of chunks) {
    for (let i = 0; i < chunk.length; i++, offset += 2) {
      const s = Math.max(-1, Math.min(1, chunk[i]));
      view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    }
  }
  return new Blob([buffer], { type: "audio/wav" });
}

async function apiError(res: Response, fallback: string): Promise<string> {
  try {
    const body = await res.json();
    return body?.message || fallback;
  } catch {
    return fallback;
  }
}

function Dot({ ok }: { ok: boolean | null }) {
  const color = ok === null ? "var(--text-tertiary)" : ok ? "var(--accent-green)" : "#f2994a";
  return <span className="w-1.5 h-1.5 rounded-full shrink-0 mt-1.5" style={{ background: color }} aria-hidden />;
}

/**
 * Speaking in the user's cloned voice: setup checklist, recording his voice
 * (a consent script with a fresh random phrase), a speakers-only test, call
 * settings, the log of what was said in his voice, and deleting it all.
 */
export default function MyVoicePanel({ outputs }: { outputs: AudioDevice[] }) {
  const [status, setStatus] = useState<VoiceStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [challenge, setChallenge] = useState<Challenge | null>(null);
  const [recording, setRecording] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [level, setLevel] = useState(0);
  const [testText, setTestText] = useState("Hi, I'm in a meeting right now. I'll call you back at five.");
  // Everything the recording needs lives here, so the auto-stop timer (created
  // in an earlier render) still sees the current script and samples.
  const rec = useRef<{
    ctx: AudioContext;
    stream: MediaStream;
    chunks: Float32Array[];
    timer: number;
    challenge: Challenge;
  } | null>(null);

  const load = useCallback(() => {
    fetch(`${API}/status`)
      .then((r) => r.json())
      .then((s: VoiceStatus) => {
        setStatus(s);
        setError(null);
      })
      .catch(() => setError("Backend offline - can't load My Voice."));
  }, []);

  useEffect(load, [load]);

  const stopTracks = () => {
    const r = rec.current;
    if (!r) return;
    window.clearInterval(r.timer);
    r.stream.getTracks().forEach((t) => t.stop());
    r.ctx.close().catch(() => {});
  };
  useEffect(() => () => stopTracks(), []);

  const startRecording = async () => {
    setError(null);
    setNote(null);
    try {
      const res = await fetch(`${API}/enroll/challenge`, { method: "POST" });
      const ch: Challenge = await res.json();
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      });
      const ctx = new AudioContext();
      const url = URL.createObjectURL(new Blob([RECORDER_WORKLET], { type: "text/javascript" }));
      await ctx.audioWorklet.addModule(url);
      URL.revokeObjectURL(url);
      const node = new AudioWorkletNode(ctx, "freya-capture");
      const chunks: Float32Array[] = [];
      node.port.onmessage = (e: MessageEvent<Float32Array>) => {
        chunks.push(e.data);
        let sum = 0;
        for (let i = 0; i < e.data.length; i++) sum += e.data[i] * e.data[i];
        setLevel(Math.min(1, Math.sqrt(sum / e.data.length) * 6));
      };
      ctx.createMediaStreamSource(stream).connect(node);
      // Timed on the audio clock, which is exactly what ends up in the file.
      const started = ctx.currentTime;
      const timer = window.setInterval(() => {
        const s = ctx.currentTime - started;
        setSeconds(s);
        if (s >= ch.max_seconds) void finishRecording();
      }, 200);
      rec.current = { ctx, stream, chunks, timer, challenge: ch };
      setChallenge(ch);
      setSeconds(0);
      setRecording(true);
    } catch {
      stopTracks();
      rec.current = null;
      setError("Couldn't start recording - allow microphone access in the browser and make sure Freya's server is running.");
    }
  };

  const cancelRecording = () => {
    stopTracks();
    rec.current = null;
    setRecording(false);
    setChallenge(null);
    setLevel(0);
  };

  const finishRecording = async () => {
    const r = rec.current;
    if (!r) return;
    const ch = r.challenge;
    stopTracks();
    rec.current = null;
    setRecording(false);
    setLevel(0);
    const wav = encodeWav(r.chunks, r.ctx.sampleRate);
    setBusy(true);
    try {
      const res = await fetch(`${API}/enroll?nonce=${encodeURIComponent(ch.nonce)}`, {
        method: "POST",
        headers: { "Content-Type": "audio/wav" },
        body: wav,
      });
      if (!res.ok) {
        setError(await apiError(res, "Couldn't save your voice."));
      } else {
        setNote("Your voice is recorded. Try it with the test below.");
        setChallenge(null);
      }
    } catch {
      setError("Couldn't reach Freya's server to save your voice.");
    } finally {
      setBusy(false);
      load();
    }
  };

  const post = async (path: string, body: object, done: string) => {
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      const res = await fetch(`${API}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) setError(await apiError(res, "That didn't work."));
      else setNote(done);
    } catch {
      setError("Couldn't reach Freya's server.");
    } finally {
      setBusy(false);
      load();
    }
  };

  const forget = async () => {
    if (!window.confirm("Delete your cloned voice from Freya and Voicebox? You can record it again later.")) return;
    setBusy(true);
    try {
      const res = await fetch(`${API}/profile`, { method: "DELETE" });
      const body = await res.json().catch(() => ({}));
      setNote(body?.message || "Your voice is deleted.");
    } catch {
      setError("Couldn't reach Freya's server.");
    } finally {
      setBusy(false);
      load();
    }
  };

  if (!status) {
    return <p className="text-[11px] text-outline">{error ?? "Loading…"}</p>;
  }

  const enough = challenge ? seconds >= challenge.min_seconds : false;
  const inputClass =
    "bg-surface-container-lowest border border-outline-variant/40 text-on-surface text-xs px-3 py-2 focus:outline-none";

  return (
    <div className="flex flex-col gap-4 text-xs">
      <p className="text-[11px] leading-relaxed text-on-surface-variant">
        Freya can answer WhatsApp and Phone Link calls and say what you dictate in your own voice. Each line
        is shown for your OK first, and everything she says as you is logged here. Sinhala and Tamil use a
        stand-in voice for now and are labelled so.
      </p>

      {/* Setup checklist */}
      <ul className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-2">
        {status.checklist.map((item) => (
          <li key={item.id} className="flex gap-2">
            <Dot ok={item.ok} />
            <div>
              <p className="text-on-surface">{item.label}</p>
              {item.ok !== true && <p className="text-[10px] text-outline leading-snug">{item.hint}</p>}
            </div>
          </li>
        ))}
      </ul>

      {/* Record */}
      <div className="border border-outline-variant/30 p-3 flex flex-col gap-3">
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-[11px] font-bold uppercase tracking-wider text-outline">
            {status.enrolled ? "Your voice is recorded" : "Record your voice"}
          </span>
          {!recording && (
            <button
              onClick={startRecording}
              disabled={busy || !status.voicebox.ok}
              title={status.voicebox.ok ? undefined : "Open Voicebox first"}
              className="ml-auto px-4 py-1.5 rounded-full text-[11px] font-bold tracking-wider uppercase bg-primary-container text-parchment disabled:opacity-40"
            >
              {status.enrolled ? "Record again" : "Start recording"}
            </button>
          )}
        </div>
        {recording && challenge && (
          <>
            <p className="text-[11px] text-outline">Read this aloud in your normal speaking voice:</p>
            <p className="text-sm leading-relaxed text-parchment bg-surface-container-lowest p-3">{challenge.script}</p>
            <div className="flex items-center gap-3">
              <div className="flex-1 h-1.5 bg-surface-container-lowest overflow-hidden rounded-full" aria-label="Microphone level">
                <div className="h-full bg-primary transition-[width] duration-100" style={{ width: `${level * 100}%` }} />
              </div>
              <span className="font-mono tabular-nums text-outline w-16 text-right">{seconds.toFixed(0)}s</span>
            </div>
            <div className="flex gap-3">
              <button
                onClick={finishRecording}
                disabled={!enough}
                className="px-4 py-1.5 rounded-full text-[11px] font-bold tracking-wider uppercase bg-primary-container text-parchment disabled:opacity-40"
              >
                {enough ? "Done - save my voice" : `Keep reading (${Math.ceil(challenge.min_seconds - seconds)}s)`}
              </button>
              <button onClick={cancelRecording} className="px-4 py-1.5 text-[11px] uppercase tracking-wider text-outline hover:text-parchment">
                Cancel
              </button>
            </div>
          </>
        )}
      </div>

      {/* Test + settings */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="flex flex-col gap-2">
          <span className="text-[11px] font-bold uppercase tracking-wider text-outline">Hear it (your speakers only)</span>
          <textarea value={testText} onChange={(e) => setTestText(e.target.value)} rows={2} maxLength={300} className={`${inputClass} resize-none`} />
          <button
            onClick={() => post("/test", { text: testText }, "Played on your speakers.")}
            disabled={busy || !status.enrolled || !testText.trim()}
            className="self-start px-4 py-1.5 rounded-full text-[11px] font-bold tracking-wider uppercase border border-outline-variant/40 text-parchment disabled:opacity-40"
          >
            Play test
          </button>
        </div>
        <div className="flex flex-col gap-2">
          <label className="flex flex-col gap-1">
            <span className="text-[11px] font-bold uppercase tracking-wider text-outline">Device for calls</span>
            <select
              aria-label="Audio device for calls"
              value={status.cable.index ?? ""}
              onChange={(e) => post("/settings", { cable_output_index: e.target.value === "" ? null : Number(e.target.value) }, "Saved.")}
              className={inputClass}
            >
              <option value="">Auto: CABLE Input</option>
              {outputs.map((d) => (
                <option key={d.index} value={d.index}>
                  {d.name}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-[11px] font-bold uppercase tracking-wider text-outline">Ask me to confirm</span>
            <select
              aria-label="When to confirm lines spoken in your voice"
              value={status.confirm}
              onChange={(e) => post("/settings", { confirm: e.target.value }, "Saved.")}
              className={inputClass}
            >
              {Object.entries(CONFIRM_LABELS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center justify-between gap-3">
            <span className="text-on-surface">Send my own mic into calls too</span>
            <input
              type="checkbox"
              checked={status.passthrough.running}
              onChange={(e) => post("/settings", { passthrough: e.target.checked }, e.target.checked ? "Your mic now reaches calls." : "Stopped.")}
              disabled={busy || !status.cable.present}
            />
          </label>
        </div>
      </div>

      {/* What she said as you */}
      {status.log.length > 0 && (
        <div className="flex flex-col gap-1">
          <span className="text-[11px] font-bold uppercase tracking-wider text-outline">Said in your voice</span>
          <ul className="flex flex-col gap-1 max-h-32 overflow-y-auto">
            {status.log.map((entry, i) => (
              <li key={`${entry.ts}-${i}`} className="text-[11px] text-on-surface-variant truncate">
                <span className="font-mono text-outline">{entry.ts.slice(5, 16).replace("T", " ")}</span>{" "}
                {entry.ok === false ? "(failed) " : ""}
                {(entry.lines ?? []).map((l) => `${l.cloned ? "" : "[stand-in] "}${l.text}`).join(" ") || entry.tool}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex items-center gap-3 min-h-[1.25rem]">
        {error && <span className="text-[11px] text-amber-300">{error}</span>}
        {!error && note && <span className="text-[11px] text-primary">{note}</span>}
        {status.enrolled && (
          <button onClick={forget} disabled={busy} className="ml-auto text-[10px] uppercase tracking-wider text-outline hover:text-amber-300 underline underline-offset-4">
            Delete my voice
          </button>
        )}
      </div>
    </div>
  );
}
