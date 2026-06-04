"use client";

import { ToolEntry } from "../hooks/useFreyaSocket";

// Tool name → emoji mapping
const TOOL_ICONS: Record<string, string> = {
  open_app:             "🚀",
  close_app:            "✖️",
  web_search:           "🔍",
  play_youtube:         "▶️",
  get_news:             "📰",
  shutdown_computer:    "⏻",
  take_screenshot:      "📸",
  open_folder:          "📁",
  get_weather:          "🌤",
  set_reminder:         "⏰",
  search_docs:          "📖",
  explain_error:        "🐛",
  open_project:         "💻",
  run_terminal_command: "⌨️",
  search_stackoverflow: "🧩",
};

interface ToolLogProps {
  toolLog: ToolEntry[];
  onClear: () => void;
}

export default function ToolLog({ toolLog, onClear }: ToolLogProps) {
  return (
    <div className="flex flex-col h-full bg-zinc-900 border border-zinc-700 rounded-2xl overflow-hidden">

      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-zinc-700">
        <h2 className="text-sm font-semibold text-zinc-200">Tool Activity</h2>
        <button
          onClick={onClear}
          className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors"
        >
          Clear
        </button>
      </div>

      {/* Log entries */}
      <div className="flex-1 overflow-y-auto px-4 py-3 flex flex-col gap-2">
        {toolLog.length === 0 ? (
          <p className="text-zinc-600 text-sm text-center mt-8">
            No tools used yet...
          </p>
        ) : (
          [...toolLog].reverse().map((entry) => (
            <div
              key={entry.id}
              className="bg-zinc-800 border border-zinc-700 rounded-xl p-3 flex flex-col gap-1"
            >
              {/* Tool name + time */}
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span>{TOOL_ICONS[entry.name] ?? "🔧"}</span>
                  <span className="text-xs font-semibold text-zinc-200">
                    {entry.name}
                  </span>
                </div>
                <span className="text-xs text-zinc-600">
                  {entry.timestamp.toLocaleTimeString([], {
                    hour: "2-digit",
                    minute: "2-digit",
                    second: "2-digit",
                  })}
                </span>
              </div>

              {/* Args */}
              {Object.keys(entry.args).length > 0 && (
                <p className="text-xs text-zinc-400 font-mono truncate">
                  {JSON.stringify(entry.args)}
                </p>
              )}

              {/* Result */}
              <p className="text-xs text-emerald-400 leading-relaxed">
                {entry.result}
              </p>
            </div>
          ))
        )}
      </div>

    </div>
  );
}