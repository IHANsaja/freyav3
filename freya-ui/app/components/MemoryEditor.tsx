"use client";

import { useState, useEffect } from "react";

interface MemoryEditorProps {
  memory: string;
  onSave: (content: string) => Promise<void>;
}

export default function MemoryEditor({ memory, onSave }: MemoryEditorProps) {
  const [value, setValue] = useState(memory);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  // Sync when memory prop updates
  useEffect(() => {
    setValue(memory);
  }, [memory]);

  const handleSave = async () => {
    setSaving(true);
    await onSave(value);
    setSaving(false);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  const isDirty = value !== memory;

  return (
    <div className="flex flex-col h-full bg-zinc-900 border border-zinc-700 rounded-2xl overflow-hidden">

      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-zinc-700">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold text-zinc-200">Memory</h2>
          {isDirty && (
            <span className="text-xs text-amber-400">● unsaved</span>
          )}
        </div>
        <button
          onClick={handleSave}
          disabled={!isDirty || saving}
          className={`text-xs px-3 py-1 rounded-lg font-medium transition-all
            ${
              saved
                ? "bg-emerald-500/20 text-emerald-400"
                : isDirty
                ? "bg-emerald-500 text-white hover:bg-emerald-600"
                : "bg-zinc-700 text-zinc-500 cursor-not-allowed"
            }`}
        >
          {saving ? "Saving..." : saved ? "✓ Saved" : "Save"}
        </button>
      </div>

      {/* Editor */}
      <textarea
        value={value}
        onChange={(e) => setValue(e.target.value)}
        spellCheck={false}
        className="flex-1 bg-transparent text-zinc-300 text-xs font-mono
                   px-4 py-3 resize-none focus:outline-none leading-relaxed"
        placeholder="Memory file is empty..."
      />

    </div>
  );
}