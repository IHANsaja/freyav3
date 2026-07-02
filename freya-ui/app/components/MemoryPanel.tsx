"use client";

import { useCallback, useEffect, useState } from "react";

interface MemoryItem {
    id: number;
    kind: string;
    subject: string;
    content: string;
    importance: number;
    due_at: string | null;
    updated_at: string;
}

const KINDS = ["all", "preference", "person", "project", "deadline", "followup", "fact", "session_summary"];

interface MemoryPanelProps {
    /** bump to force a refetch (wired to the memory_changed WS event) */
    refreshKey?: number;
}

/** Structured memory browser: filter, search, inline edit, add, forget. */
export default function MemoryPanel({ refreshKey = 0 }: MemoryPanelProps) {
    const [items, setItems] = useState<MemoryItem[]>([]);
    const [kind, setKind] = useState("all");
    const [query, setQuery] = useState("");
    const [editingId, setEditingId] = useState<number | null>(null);
    const [draft, setDraft] = useState("");
    const [adding, setAdding] = useState(false);
    const [newItem, setNewItem] = useState({ kind: "fact", subject: "", content: "" });

    const load = useCallback(async () => {
        const params = new URLSearchParams();
        if (kind !== "all") params.set("kind", kind);
        if (query.trim()) params.set("q", query.trim());
        try {
            const res = await fetch(`http://localhost:8000/memory/items?${params}`);
            const data = await res.json();
            setItems(data.items ?? []);
        } catch (e) {
            console.error("memory load failed", e);
        }
    }, [kind, query]);

    useEffect(() => {
        load();
    }, [load, refreshKey]);

    const saveEdit = async (id: number) => {
        await fetch(`http://localhost:8000/memory/items/${id}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ content: draft }),
        });
        setEditingId(null);
        load();
    };

    const forget = async (id: number) => {
        await fetch(`http://localhost:8000/memory/items/${id}`, { method: "DELETE" });
        load();
    };

    const addItem = async () => {
        if (!newItem.content.trim()) return;
        await fetch("http://localhost:8000/memory/items", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(newItem),
        });
        setNewItem({ kind: "fact", subject: "", content: "" });
        setAdding(false);
        load();
    };

    return (
        <div className="flex flex-col gap-3">
            {/* Filter row */}
            <div className="flex items-center gap-2 flex-wrap">
                {KINDS.map((k) => (
                    <button
                        key={k}
                        onClick={() => setKind(k)}
                        className={`px-3 py-1 rounded-full text-[9px] font-bold tracking-widest uppercase border transition-all ${
                            kind === k
                                ? "bg-primary-container text-parchment border-primary-container"
                                : "text-outline border-outline-variant/30 hover:border-primary/50"
                        }`}
                    >
                        {k.replace("_", " ")}
                    </button>
                ))}
            </div>
            <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="SEARCH MEMORY..."
                spellCheck={false}
                className="w-full bg-surface-container-lowest border border-outline-variant/40 text-on-surface text-[11px] px-3 py-2 focus:outline-none focus:border-primary-container font-mono tracking-wider"
                style={{ borderRadius: 0 }}
            />

            {/* Items */}
            <div className="max-h-56 overflow-y-auto flex flex-col">
                {items.length === 0 && (
                    <p className="text-[10px] font-mono text-outline uppercase tracking-widest py-3">
                        No memories match.
                    </p>
                )}
                {items.map((item) => (
                    <div key={item.id} className="py-2 border-b border-outline-variant/15 group">
                        <div className="flex items-center gap-2">
                            <span className="px-2 py-0.5 text-[8px] font-bold uppercase tracking-widest bg-secondary-container/40 text-parchment rounded-full">
                                {item.kind}
                            </span>
                            <span className="text-[11px] font-semibold text-parchment truncate">
                                {item.subject}
                            </span>
                            {item.due_at && (
                                <span className="text-[9px] font-mono text-primary">due {item.due_at}</span>
                            )}
                            <div className="ml-auto flex gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                                <button
                                    onClick={() => {
                                        setEditingId(item.id);
                                        setDraft(item.content);
                                    }}
                                    className="text-[9px] font-mono uppercase text-outline hover:text-parchment"
                                >
                                    edit
                                </button>
                                <button
                                    onClick={() => forget(item.id)}
                                    className="text-[9px] font-mono uppercase text-outline hover:text-secondary"
                                >
                                    forget
                                </button>
                            </div>
                        </div>
                        {editingId === item.id ? (
                            <div className="flex gap-2 mt-1">
                                <input
                                    value={draft}
                                    onChange={(e) => setDraft(e.target.value)}
                                    onKeyDown={(e) => e.key === "Enter" && saveEdit(item.id)}
                                    autoFocus
                                    className="flex-1 bg-surface-container-lowest border border-primary-container/60 text-on-surface text-[11px] px-2 py-1 focus:outline-none font-mono"
                                    style={{ borderRadius: 0 }}
                                />
                                <button
                                    onClick={() => saveEdit(item.id)}
                                    className="text-[9px] font-bold uppercase text-primary"
                                >
                                    save
                                </button>
                            </div>
                        ) : (
                            <p className="text-[11px] text-on-surface-variant leading-snug mt-0.5">
                                {item.content}
                            </p>
                        )}
                    </div>
                ))}
            </div>

            {/* Add */}
            {adding ? (
                <div className="flex flex-col gap-2 border border-outline-variant/30 p-3" style={{ borderRadius: 0 }}>
                    <div className="flex gap-2">
                        <select
                            value={newItem.kind}
                            onChange={(e) => setNewItem({ ...newItem, kind: e.target.value })}
                            className="bg-surface-container-lowest border border-outline-variant/40 text-[10px] font-mono uppercase px-2 py-1"
                            style={{ borderRadius: 0 }}
                        >
                            {KINDS.filter((k) => k !== "all" && k !== "session_summary").map((k) => (
                                <option key={k} value={k}>{k}</option>
                            ))}
                        </select>
                        <input
                            value={newItem.subject}
                            onChange={(e) => setNewItem({ ...newItem, subject: e.target.value })}
                            placeholder="Subject"
                            className="flex-1 bg-surface-container-lowest border border-outline-variant/40 text-[11px] px-2 py-1 font-mono focus:outline-none focus:border-primary-container"
                            style={{ borderRadius: 0 }}
                        />
                    </div>
                    <input
                        value={newItem.content}
                        onChange={(e) => setNewItem({ ...newItem, content: e.target.value })}
                        onKeyDown={(e) => e.key === "Enter" && addItem()}
                        placeholder="What should Freya remember?"
                        className="bg-surface-container-lowest border border-outline-variant/40 text-[11px] px-2 py-1 font-mono focus:outline-none focus:border-primary-container"
                        style={{ borderRadius: 0 }}
                    />
                    <div className="flex gap-3 justify-end">
                        <button onClick={() => setAdding(false)} className="text-[9px] font-mono uppercase text-outline">
                            cancel
                        </button>
                        <button onClick={addItem} className="text-[9px] font-bold uppercase text-primary">
                            add
                        </button>
                    </div>
                </div>
            ) : (
                <button
                    onClick={() => setAdding(true)}
                    className="self-start px-4 py-1.5 rounded-full text-[10px] font-bold tracking-widest uppercase border border-outline-variant/40 text-outline hover:border-primary/60 hover:text-parchment transition-all"
                >
                    + Add memory
                </button>
            )}
        </div>
    );
}
