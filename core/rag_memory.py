"""
Semantic RAG memory & document knowledge.

core/memory.py keeps a flat markdown log that's pasted wholesale into the system prompt —
fine for a few facts, useless once it grows or when Ihan asks about a specific document.
This module adds *retrieval*: Gemini embeddings (text-embedding-004) over the memory file
plus any folders Ihan points at, stored in a local Chroma vector DB. Freya can then:

  • recall(query)      — semantically search everything she knows / has indexed
  • index_folder(path) — ingest a folder of notes/docs so "what did my notes say about X" works

Gated behind config `rag.enabled`. Degrades to a clear message if chromadb is missing.
"""

import os
import hashlib

from config import get_agent_api_key
from core.registry import tool, OBJ, P, STR

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
    return _collection


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


# ══════════════════════════════════════════════
#  TOOLS
# ══════════════════════════════════════════════
@tool(
    "recall",
    "Semantically search Freya's long-term memory and any indexed documents for relevant info. "
    "Use when Ihan asks what you remember about something, or references his notes/files.",
    OBJ({"query": P(STR, "What to recall, in natural language")}, ["query"]),
    gate="rag.enabled",
)
def recall(args, ctx) -> str:
    query = (args.get("query") or "").strip()
    if not query:
        return "What would you like me to recall?"
    try:
        col = _get_collection()
        if col.count() == 0:
            index_memory_file()
        vec = _embed([query])[0]
        res = col.query(query_embeddings=[vec], n_results=5)
        docs = (res.get("documents") or [[]])[0]
        if not docs:
            return f"I don't have anything indexed about '{query}' yet."
        joined = " … ".join(d.strip().replace("\n", " ")[:400] for d in docs)
        return f"Here's what I found about '{query}': {joined}"
    except Exception as e:
        return f"Recall failed: {e}"


@tool(
    "index_folder",
    "Index a folder of documents/notes into Freya's knowledge base so she can recall from them "
    "later. Reads common text files recursively.",
    OBJ({"path": P(STR, "Absolute folder path to index")}, ["path"]),
    gate="rag.enabled",
)
def index_folder(args, ctx) -> str:
    path = os.path.expanduser(args.get("path", ""))
    if not os.path.isdir(path):
        return f"'{path}' isn't a folder I can read."
    total, files = 0, 0
    try:
        for root, _dirs, names in os.walk(path):
            if any(skip in root for skip in ("node_modules", ".git", "__pycache__", ".next")):
                continue
            for name in names:
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
