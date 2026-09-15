"use client";
import { useState } from "react";
import { TOOLS, isDrawing, type Drawing } from "./drawingTools";
function Editor({
  drawing,
  onSave,
}: {
  drawing: Drawing;
  onSave: (d: Drawing) => void;
}) {
  const [draft, setDraft] = useState(drawing);
  const [error, setError] = useState("");
  const patch = (change: Partial<Drawing>) =>
    setDraft((d) => ({ ...d, ...change }));
  return (
    <form
      className="drawing-editor"
      onSubmit={(e) => {
        e.preventDefault();
        if (!isDrawing(draft)) {
          setError("Check the coordinates and style values.");
          return;
        }
        onSave(draft);
        setError("Saved.");
      }}
    >
      <h3>Edit {TOOLS[draft.kind].label}</h3>
      <fieldset disabled={drawing.locked}>
        <div className="risk-inputs">
          <label>
            Label
            <input
              maxLength={500}
              value={draft.text ?? ""}
              onChange={(e) => patch({ text: e.target.value })}
            />
          </label>
          <label>
            Color
            <input
              type="color"
              value={draft.color ?? "#759aff"}
              onChange={(e) => patch({ color: e.target.value })}
            />
          </label>
          <label>
            Line width
            <select
              value={draft.width ?? 2}
              onChange={(e) => patch({ width: +e.target.value })}
            >
              {[1, 2, 3, 4].map((n) => (
                <option key={n}>{n}</option>
              ))}
            </select>
          </label>
          {["long", "short"].includes(draft.kind) && (
            <label>
              Reward / risk ratio
              <input
                type="number"
                min="0.1"
                max="20"
                step="0.1"
                value={draft.rewardRatio ?? 2}
                onChange={(e) => patch({ rewardRatio: +e.target.value })}
              />
            </label>
          )}
        </div>
        {draft.kind !== "brush" &&
          draft.points.map((p, i) => (
            <div className="anchor-inputs" key={i}>
              <label>
                Anchor {i + 1} · UTC
                <input
                  type="datetime-local"
                  value={
                    Number.isFinite(p.time) &&
                    p.time >= 0 &&
                    p.time <= 4102444800
                      ? new Date(p.time * 1000).toISOString().slice(0, 16)
                      : ""
                  }
                  onChange={(e) =>
                    patch({
                      points: draft.points.map((v, j) =>
                        i === j
                          ? {
                              ...v,
                              time: Date.parse(e.target.value + "Z") / 1000,
                            }
                          : v,
                      ),
                    })
                  }
                />
              </label>
              <label>
                Price
                <input
                  type="number"
                  step="any"
                  min="0.00000001"
                  value={p.price}
                  onChange={(e) =>
                    patch({
                      points: draft.points.map((v, j) =>
                        i === j ? { ...v, price: +e.target.value } : v,
                      ),
                    })
                  }
                />
              </label>
            </div>
          ))}
        <button className="subtle" type="submit">
          Save drawing changes
        </button>
      </fieldset>
      <p aria-live="polite">
        {drawing.locked ? "Unlock this drawing to edit it." : error}
      </p>
    </form>
  );
}
export default function DrawingInspector({
  drawings,
  onChange,
}: {
  drawings: Drawing[];
  onChange: (d: Drawing[]) => void;
}) {
  const [selected, setSelected] = useState<string | null>(null);
  const drawing = drawings.find((d) => d.id === selected);
  return (
    <section className="learning-panel">
      <h2>Drawing objects</h2>
      <p className="muted">
        Edit exact coordinates and styles; hide or lock individual drawings.
        Locks protect editing and erasing. Undo/redo tracks local edits.
        Position drawings are illustrative, not executable orders.
      </p>
      <div className="object-list">
        {drawings.map((d) => (
          <div key={d.id}>
            <button
              aria-pressed={selected === d.id}
              onClick={() => setSelected(d.id)}
            >
              {TOOLS[d.kind].label}
              {d.author === "freya" ? " · Freya" : ""}
            </button>
            <button
              aria-label={`${d.hidden ? "Show" : "Hide"} ${TOOLS[d.kind].label}`}
              onClick={() =>
                onChange(
                  drawings.map((v) =>
                    v.id === d.id ? { ...v, hidden: !v.hidden } : v,
                  ),
                )
              }
            >
              {d.hidden ? "Show" : "Hide"}
            </button>
            <button
              aria-label={`${d.locked ? "Unlock" : "Lock"} ${TOOLS[d.kind].label}`}
              onClick={() =>
                onChange(
                  drawings.map((v) =>
                    v.id === d.id ? { ...v, locked: !v.locked } : v,
                  ),
                )
              }
            >
              {d.locked ? "Unlock" : "Lock"}
            </button>
            <button
              disabled={d.locked}
              onClick={() => onChange(drawings.filter((v) => v.id !== d.id))}
            >
              Delete
            </button>
          </div>
        ))}
      </div>
      {!drawings.length && (
        <p>Choose a drawing tool and add an object to the chart.</p>
      )}
      {drawing && (
        <Editor
          key={JSON.stringify(drawing)}
          drawing={drawing}
          onSave={(next) =>
            onChange(drawings.map((d) => (d.id === next.id ? next : d)))
          }
        />
      )}
    </section>
  );
}
