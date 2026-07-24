"use client";

import { useCallback, useEffect, useState } from "react";

interface SafetyConfig {
  allowed_roots: string[];
  approval_mode: string;
  unrestricted: boolean;
  approval_timeout_s: number;
  defaults: string[];
}

const API = "http://localhost:8000/safety";

/**
 * Editor for `safety.allowed_roots` and the approval gate.
 *
 * These control which folders Freya is allowed to write to or delete from
 * (core/safety.py). Until now they could only be changed by hand-editing
 * config/freya_config.json and restarting, which meant most people either left
 * the default sandbox in place or switched `unrestricted` on wholesale.
 *
 * Paths are validated server-side (the folder must actually exist) so a typo
 * can't silently widen or break the sandbox.
 */
export default function AccessControlPanel() {
  const [cfg, setCfg] = useState<SafetyConfig | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const load = useCallback(() => {
    fetch(API)
      .then((r) => r.json())
      .then((d: SafetyConfig) => setCfg(d))
      .catch(() => setError("Backend offline — can't load access control."));
  }, []);

  useEffect(load, [load]);

  const save = useCallback(
    async (patch: Partial<SafetyConfig> & { allowed_roots?: string[] }) => {
      setBusy(true);
      setError(null);
      try {
        const res = await fetch(API, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(patch),
        });
        const body = await res.json();
        if (!res.ok) {
          // The backend returns a safe, specific message for user errors
          // (e.g. "'X' is not a folder that exists on this machine").
          setError(body?.message || "Couldn't save access control.");
          return false;
        }
        setSaved(true);
        setTimeout(() => setSaved(false), 1800);
        load();
        return true;
      } catch {
        setError("Backend offline — change not saved.");
        return false;
      } finally {
        setBusy(false);
      }
    },
    [load]
  );

  if (!cfg) {
    return (
      <p className="text-[11px] text-outline/70">
        {error ?? "Loading access control…"}
      </p>
    );
  }

  const roots = cfg.allowed_roots;

  const addPath = async () => {
    const p = draft.trim();
    if (!p) return;
    if (roots.includes(p)) {
      setError("That folder is already allowed.");
      return;
    }
    if (await save({ allowed_roots: [...roots, p] })) setDraft("");
  };

  return (
    <div className="flex flex-col gap-3">
      <p className="text-[10px] leading-relaxed text-outline/70">
        Folders Freya may modify. Leave the list empty to use the safe default
        sandbox (your home folder and the Freya project).
      </p>

      {/* Current allow-list */}
      <ul className="flex flex-col gap-1">
        {roots.length === 0 && (
          <li className="text-[10px] font-mono text-outline/60 border border-outline-variant/25 px-3 py-2">
            {cfg.defaults.map((d) => (
              <span key={d} className="block truncate" title={d}>
                {d} <span className="text-outline/40">(default)</span>
              </span>
            ))}
          </li>
        )}
        {roots.map((p) => (
          <li
            key={p}
            className="flex items-center gap-2 border border-outline-variant/40 px-3 py-2 bg-surface-container-lowest"
          >
            <span className="flex-1 text-[10px] font-mono truncate text-on-surface" title={p}>
              {p}
            </span>
            <button
              onClick={() => save({ allowed_roots: roots.filter((r) => r !== p) })}
              disabled={busy}
              aria-label={`Remove ${p}`}
              className="text-outline hover:text-primary transition-colors text-xs disabled:opacity-40"
            >
              ✕
            </button>
          </li>
        ))}
      </ul>

      {/* Add a path */}
      <div className="flex gap-2">
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              addPath();
            }
          }}
          placeholder="F:/Projects/MyFolder"
          spellCheck={false}
          className="flex-1 min-w-0 bg-surface-container-lowest border border-outline-variant/40 text-on-surface
                     text-[11px] font-mono px-3 py-2 focus:outline-none focus:border-primary-container"
          style={{ borderRadius: "0px" }}
        />
        <button
          onClick={addPath}
          disabled={busy || !draft.trim()}
          className="px-4 py-2 text-[10px] font-semibold uppercase tracking-widest border
                     border-primary-container text-primary hover:bg-primary-container/20
                     transition-colors disabled:opacity-40"
          style={{ borderRadius: "0px" }}
        >
          Add
        </button>
      </div>

      {/* Approval gate */}
      <div className="flex flex-col gap-2 pt-1">
        <label className="flex items-center justify-between gap-3 cursor-pointer">
          <span className="text-[10px] uppercase tracking-wider text-outline">
            Confirm sensitive actions
          </span>
          <input
            type="checkbox"
            checked={cfg.approval_mode === "confirm"}
            disabled={busy}
            onChange={(e) => save({ approval_mode: e.target.checked ? "confirm" : "off" })}
            className="accent-[var(--accent-red)] w-4 h-4"
          />
        </label>

        <label className="flex items-center justify-between gap-3 cursor-pointer">
          <span className="text-[10px] uppercase tracking-wider text-outline">
            Unrestricted mode
            <span className="block text-[9px] normal-case tracking-normal text-outline/50">
              Disables the folder sandbox entirely
            </span>
          </span>
          <input
            type="checkbox"
            checked={cfg.unrestricted}
            disabled={busy}
            onChange={(e) => save({ unrestricted: e.target.checked })}
            className="accent-[var(--danger)] w-4 h-4"
          />
        </label>
      </div>

      {cfg.unrestricted && (
        <p className="text-[10px] leading-relaxed" style={{ color: "var(--danger)" }}>
          Unrestricted: Freya can modify files anywhere on this machine.
        </p>
      )}
      {error && (
        <p className="text-[10px] leading-relaxed" style={{ color: "var(--danger)" }}>
          {error}
        </p>
      )}
      {saved && (
        <p className="text-[10px]" style={{ color: "var(--accent-green)" }}>
          Saved.
        </p>
      )}
    </div>
  );
}
