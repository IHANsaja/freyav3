"""
Semantic RAG memory & document knowledge.

core/memory.py keeps a flat markdown log that's pasted wholesale into the system prompt —
fine for a few facts, useless once it grows or when the user asks about a specific document.
This module adds *retrieval*: Gemini embeddings (text-embedding-004) over the memory file
plus any folders the user points at, stored in a local Chroma vector DB. Freya can then:

  • recall(query)      — semantically search everything she knows / has indexed
  • index_folder(path) — ingest a folder of notes/docs so "what did my notes say about X" works

Gated behind config `rag.enabled`. Degrades to a clear message if chromadb is missing.
"""

import os
import hashlib

from config import get_agent_api_key
from core.registry import tool, OBJ, P, STR
from core.user_paths import resolve_user_path

_DB_DIR = os.path.join(os.path.dirname(__file__), "..", "memory", "rag_db")
_EMBED_MODEL = "gemini-embedding-001"
_TEXT_EXT = {".md", ".txt", ".py", ".js", ".ts", ".json", ".csv", ".rst", ".html"}
_collection = None


def _get_collection():
    global _collection
    if _collection is not None:
        return _collection
    import chromadb
    os.makedirs(_DB_DIR, exist_ok=True)
    client = chromadb.PersistentClient(path=os.path.abspath(_DB_DIR))
    _collection = client.get_or_create_collection("freya_knowledge")
    try:
        _purge_stale_memory_chunks(_collection)
    except Exception:
        pass
    return _collection


_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_MEMORY_DIR = os.path.join(_PROJECT_ROOT, "memory")


def _is_template(path: str) -> bool:
    return ".example." in os.path.basename(path).lower()


def _purge_stale_memory_chunks(col) -> int:
    """Drop chunks indexed from files in memory/ that are gone or are the
    placeholder templates. Left in, recall() answered "what do you know about
    me" with the template's "[Your Name]" lines and the pre-structured-store
    markdown log. Folders the user indexed elsewhere are never touched."""
    stale = []
    got = col.get(include=["metadatas"])
    for chunk_id, meta in zip(got.get("ids") or [], got.get("metadatas") or []):
        source = str((meta or {}).get("source") or "")
        if not source or source.startswith("web:") or source == "memory":
            continue
        path = os.path.abspath(source if os.path.isabs(source)
                               else os.path.join(_PROJECT_ROOT, source))
        try:
            if os.path.commonpath([path, _MEMORY_DIR]) != _MEMORY_DIR:
                continue
        except ValueError:      # different drive on Windows
            continue
        if _is_template(path) or not os.path.exists(path):
            stale.append(chunk_id)
    if stale:
        col.delete(ids=stale)
        print(f"  [rag] removed {len(stale)} stale memory chunk(s).")
    return len(stale)


def _embed(texts: list[str]) -> list[list[float]]:
    from google import genai
    client = genai.Client(api_key=get_agent_api_key())
    resp = client.models.embed_content(model=_EMBED_MODEL, contents=texts)
    return [list(e.values) for e in resp.embeddings]


def _chunk(text: str, size: int = 1200, overlap: int = 150) -> list[str]:
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []
    out, i = [], 0
    while i < len(text):
        out.append(text[i:i + size])
        i += size - overlap
    return out


def _add(docs: list[str], source: str):
    if not docs:
        return 0
    col = _get_collection()
    embeds = _embed(docs)
    ids = [hashlib.md5(f"{source}:{i}:{d[:40]}".encode()).hexdigest() for i, d in enumerate(docs)]
    col.upsert(ids=ids, documents=docs, embeddings=embeds,
               metadatas=[{"source": source} for _ in docs])
    return len(docs)


def index_memory_file():
    """Index the markdown memory so recall() always has the basics. Best-effort."""
    try:
        from core.memory import MEMORY_PATH
        if os.path.exists(MEMORY_PATH):
            with open(MEMORY_PATH, "r", encoding="utf-8") as f:
                _add(_chunk(f.read()), "memory")
    except Exception:
        pass


def upsert_memory_item(doc_id: str, text: str):
    """Mirror one structured-memory item into the vector store (used by the
    `remember` tool so semantic recall covers voice-saved memories too)."""
    col = _get_collection()
    col.upsert(
        ids=[hashlib.md5(doc_id.encode()).hexdigest()],
        documents=[text],
        embeddings=_embed([text]),
        metadatas=[{"source": doc_id}],
    )


# ══════════════════════════════════════════════
#  TOOLS
# ══════════════════════════════════════════════
@tool(
    "recall",
    "Semantically search Freyja's long-term memory and any indexed documents for relevant info. "
    "Use when the user asks what you remember about something, or references his notes/files.",
    OBJ({"query": P(STR)}, ["query"]),
    gate="rag.enabled",
)
def recall(args, ctx) -> str:
    query = (args.get("query") or "").strip()
    if not query:
        return "What would you like me to recall?"

    # Structured-memory FTS hits first — exact, cheap, no API call.
    fts_lines: list[str] = []
    try:
        from core.memory_store import get_store
        for item in get_store().search(query, limit=5):
            fts_lines.append(f"[memory #{item.id}] {item.subject}: {item.content}")
    except Exception:
        pass

    try:
        col = _get_collection()
        if col.count() == 0:
            index_memory_file()
        vec = _embed([query])[0]
        res = col.query(query_embeddings=[vec], n_results=5)
        docs = (res.get("documents") or [[]])[0]
    except Exception as e:
        if fts_lines:
            return f"From my memory about '{query}': " + " … ".join(fts_lines)
        return f"Recall failed: {e}"

    joined_parts = fts_lines + [d.strip().replace("\n", " ")[:400] for d in docs]
    if not joined_parts:
        return f"I don't have anything indexed about '{query}' yet."
    return f"Here's what I found about '{query}': " + " … ".join(joined_parts[:8])


@tool(
    "index_folder",
    "Index a folder of documents/notes into Freyja's knowledge base so she can recall from them "
    "later. Reads common text files recursively.",
    OBJ({"path": P(STR)}, ["path"]),
    gate="rag.enabled",
)
def index_folder(args, ctx) -> str:
    path = resolve_user_path(args.get("path", ""))
    if not os.path.isdir(path):
        return f"'{path}' isn't a folder I can read."
    total, files = 0, 0
    try:
        for root, _dirs, names in os.walk(path):
            if any(skip in root for skip in ("node_modules", ".git", "__pycache__", ".next",
                                             "rag_db", "browser_profile")):
                continue
            for name in names:
                if _is_template(name):
                    continue   # placeholder templates, not knowledge
                if os.path.splitext(name)[1].lower() in _TEXT_EXT:
                    fp = os.path.join(root, name)
                    try:
                        with open(fp, "r", encoding="utf-8", errors="replace") as f:
                            total += _add(_chunk(f.read()), fp)
                        files += 1
                    except Exception:
                        continue
                    if files >= 200:
                        break
        return f"Indexed {total} chunks from {files} files under {path}. You can ask me about them now."
    except Exception as e:
        return f"Indexing failed: {e}"
