"use client";
import { useState } from "react";
import type { Session } from "./types";
import { sizePracticeTrade } from "./practiceMath";
const CHECKS = [
  "I wrote a thesis and a reason it could be wrong.",
  "I understand the order type and its trigger.",
  "I planned an exit and an affordable hypothetical loss.",
  "I checked fees, slippage and whether my data is current.",
  "I can explain the decision without relying on a headline or AI instruction.",
];
export default function PracticeCoach({
  session,
  onQuantity,
}: {
  session: Session;
  onQuantity: (q: string) => void;
}) {
  const [entry, setEntry] = useState(session.candles.at(-1)!.close);
  const [stop, setStop] = useState("");
  const [target, setTarget] = useState("");
  const [risk, setRisk] = useState("1");
  const [checks, setChecks] = useState<boolean[]>(() => {
    try {
      const raw = JSON.parse(
        localStorage.getItem(`freya-checklist-${session.id}`) ?? "[]",
      );
      return Array.isArray(raw) && raw.length === CHECKS.length
        ? raw.map((v) => v === true)
        : [];
    } catch {
      return [];
    }
  });
  const [saved, setSaved] = useState("");
  const [copied, setCopied] = useState(false);
  const result = sizePracticeTrade(
    +session.equity,
    +session.cash - +session.reserved_cash,
    +entry,
    +stop,
    +target,
    +risk,
    +session.fee,
    +session.slippage,
  );
  const money = (n: number) =>
    n.toLocaleString(undefined, { style: "currency", currency: "USD" });
  function toggle(i: number) {
    const next = CHECKS.map((_, j) => (j === i ? !checks[j] : !!checks[j]));
    setChecks(next);
    try {
      localStorage.setItem(
        `freya-checklist-${session.id}`,
        JSON.stringify(next),
      );
      setSaved("Checklist saved for this session.");
    } catch {
      setSaved("Storage unavailable; checklist is kept only on this page.");
    }
  }
  return (
    <section className="learning-panel">
      <h2>Practice coach</h2>
      <div className="coach-grid">
        <div>
          <h3>1. Plan a hypothetical loss</h3>
          <p className="muted">
            Long-spot calculator. The 1% starting value is an editable example,
            not a recommendation. No order is placed.
          </p>
          <div className="risk-inputs">
            {[
              ["Entry price", entry, setEntry],
              ["Stop price", stop, setStop],
              ["Target price", target, setTarget],
              ["Hypothetical risk %", risk, setRisk],
            ].map(([label, value, setter]) => (
              <label key={String(label)}>
                {String(label)}
                <input
                  inputMode="decimal"
                  value={String(value)}
                  onChange={(e) =>
                    (setter as (v: string) => void)(e.target.value)
                  }
                />
              </label>
            ))}
          </div>
          {result ? (
            <>
              <dl className="risk-results">
                <div>
                  <dt>Risk budget</dt>
                  <dd>{money(result.budget)}</dd>
                </div>
                <div>
                  <dt>Calculated quantity</dt>
                  <dd>{result.units.toFixed(8)}</dd>
                </div>
                <div>
                  <dt>Estimated loss at stop</dt>
                  <dd>{money(result.estimatedLoss)}</dd>
                </div>
                <div>
                  <dt>Estimated reward / risk</dt>
                  <dd>{result.ratio.toFixed(2)} : 1</dd>
                </div>
              </dl>
              {result.cashLimited && (
                <p>Quantity is capped by available cash.</p>
              )}
              {result.ratio <= 0 && (
                <p className="negative">
                  Estimated costs exceed the target gain.
                </p>
              )}
              <button
                className="subtle"
                disabled={result.units <= 0}
                onClick={() => {
                  onQuantity(result.units.toFixed(8));
                  setCopied(true);
                }}
              >
                Copy quantity to order ticket
              </button>
            </>
          ) : (
            <p>
              Enter positive prices with stop below entry and target above
              entry, and a risk percentage between 0 and 100.
            </p>
          )}
          {copied && (
            <p role="status">
              Quantity copied to the order ticket. Review its order type and
              prices before submitting.
            </p>
          )}
          <p className="muted">
            Includes the session’s estimated round-trip fees and slippage. Gaps
            can exceed the planned loss. This does not create a stop order.
          </p>
        </div>
        <div>
          <h3>2. Pause before the trade</h3>
          <p className="muted">
            A self-check, not a buy/sell score. Revisit it whenever your plan
            changes.
          </p>
          {CHECKS.map((text, i) => (
            <label className="checklist-row" key={text}>
              <input
                type="checkbox"
                checked={!!checks[i]}
                onChange={() => toggle(i)}
              />
              <span>{text}</span>
            </label>
          ))}
          <p>
            {checks.filter(Boolean).length}/{CHECKS.length} reviewed
          </p>
          <p className="muted" aria-live="polite">
            {saved}
          </p>
          <p className="muted">
            Thesis recorded: {session.thesis ? "yes" : "not yet"} · fills
            observed: {session.fills.length}
          </p>
        </div>
      </div>
    </section>
  );
}
