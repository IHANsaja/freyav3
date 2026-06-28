"use client";

import { ToolEntry } from "../hooks/useFreyaSocket";

/**
 * Turns Freya's tool activity into contextual visual cards that appear while she
 * talks about them — e.g. asking for world news renders the headlines as small
 * boxes, weather renders a weather tile, a screen scan renders element chips, etc.
 * Everything is parsed from the tool result strings the backend already emits, so
 * no backend changes are needed.
 */

interface Card {
  id: number;
  kind: string;
  title: string;
  icon: string;
  entry: ToolEntry;
}

const NEWS_TOOLS = new Set(["get_world_news", "get_news"]);
const SEARCH_TOOLS = new Set([
  "web_search", "play_youtube", "search_docs", "search_stackoverflow", "explain_error",
]);
const APP_TOOLS = new Set(["open_app", "close_app", "open_folder", "open_project"]);
const STATUS_TOOLS = new Set([
  "dispatch_agent", "check_agents", "browser_task", "schedule_task",
  "list_tasks", "cancel_task", "watch_screen", "stop_watching",
]);

function kindFor(name: string): { kind: string; icon: string; title: string } {
  const n = name.replace(/^⚡\s*/, "");
  if (NEWS_TOOLS.has(n)) return { kind: "news", icon: "📰", title: "WORLD NEWS" };
  if (n === "get_weather") return { kind: "weather", icon: "🌦️", title: "WEATHER" };
  if (n === "read_screen_elements") return { kind: "screen", icon: "🎯", title: "SCREEN ELEMENTS" };
  if (n === "recall" || n === "index_folder") return { kind: "recall", icon: "🧠", title: "MEMORY" };
  if (SEARCH_TOOLS.has(n)) return { kind: "search", icon: "🔎", title: "SEARCH" };
  if (APP_TOOLS.has(n)) return { kind: "app", icon: "🚀", title: "SYSTEM" };
  if (STATUS_TOOLS.has(n) || ["agent", "browser", "schedule", "ambient", "mcp"].includes(n))
    return { kind: "status", icon: "🤖", title: n.toUpperCase().replace(/_/g, " ") };
  return { kind: "generic", icon: "⚙️", title: n.toUpperCase().replace(/_/g, " ") };
}

function parseNews(result: string): string[] {
  return result
    .split(/\d+\.\s+/)
    .slice(1)
    .map((p) => p.replace(/;\s*$/, "").replace(/\.\s*Read these[\s\S]*$/i, "").trim())
    .filter(Boolean)
    .slice(0, 6);
}

function parseElements(result: string): string[] {
  return result
    .split("\n")
    .slice(1)
    .map((l) => l.trim())
    .filter(Boolean)
    .slice(0, 10);
}

const SHELL =
  "animate-card-in border border-outline-variant/30 bg-surface-container-lowest/70 " +
  "backdrop-blur-sm p-3 flex flex-col gap-2";

function CardHeader({ icon, title, time }: { icon: string; title: string; time: Date }) {
  return (
    <div className="flex items-center justify-between">
      <span className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-widest text-primary">
        <span className="text-sm">{icon}</span>
        {title}
      </span>
      <span className="text-[9px] text-outline-variant font-mono">
        {time.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
      </span>
    </div>
  );
}

function CardBody({ card }: { card: Card }) {
  const { kind, entry } = card;

  if (kind === "news") {
    const headlines = parseNews(entry.result);
    return (
      <div className="grid grid-cols-1 gap-1.5">
        {headlines.map((h, i) => (
          <div
            key={i}
            className="animate-card-in border-l-2 border-primary/60 bg-surface-dim/60 px-2.5 py-1.5 text-[11px] text-parchment leading-snug"
            style={{ animationDelay: `${i * 70}ms` }}
          >
            <span className="text-primary font-bold mr-1.5">{i + 1}</span>
            {h}
          </div>
        ))}
      </div>
    );
  }

  if (kind === "weather") {
    return (
      <div className="text-lg font-bold text-parchment tracking-wide">
        {entry.result.replace(/^Weather in\s*/i, "")}
      </div>
    );
  }

  if (kind === "screen") {
    const els = parseElements(entry.result);
    return (
      <div className="flex flex-wrap gap-1.5">
        {els.length === 0 ? (
          <span className="text-[10px] text-outline italic">{entry.result}</span>
        ) : (
          els.map((e, i) => (
            <span
              key={i}
              className="animate-card-in text-[10px] font-mono px-2 py-1 bg-surface-dim/70 border border-outline-variant/30 text-on-surface"
              style={{ animationDelay: `${i * 40}ms` }}
            >
              {e}
            </span>
          ))
        )}
      </div>
    );
  }

  if (kind === "search" || kind === "app") {
    const q = (entry.args?.query ?? entry.args?.name ?? entry.args?.text ?? "") as string;
    return (
      <div className="flex flex-col gap-1">
        {q && <div className="text-[12px] text-parchment font-medium">{q}</div>}
        <div className="text-[10px] text-outline leading-snug">{entry.result}</div>
      </div>
    );
  }

  // recall / status / generic
  return (
    <div className="text-[11px] text-on-surface leading-relaxed whitespace-pre-wrap">
      {entry.result || "…"}
    </div>
  );
}

export default function VisualCards({ toolLog }: { toolLog: ToolEntry[] }) {
  // Newest cards first; cap so the panel stays glanceable.
  const cards: Card[] = [...toolLog]
    .slice(-10)
    .reverse()
    .map((entry) => {
      const meta = kindFor(entry.name);
      return { id: entry.id, ...meta, entry };
    })
    .slice(0, 6);

  if (cards.length === 0) {
    return (
      <div className="text-[10px] text-outline-variant italic uppercase tracking-widest px-1 py-4">
        Visuals will appear here as Freya acts…
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {cards.map((card) => (
        <div key={card.id} className={SHELL}>
          <CardHeader icon={card.icon} title={card.title} time={card.entry.timestamp} />
          <CardBody card={card} />
        </div>
      ))}
    </div>
  );
}
