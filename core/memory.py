"""
Memory façade — same public API as before (load_memory / build_system_prompt /
update_memory / TranscriptCollector), now backed by the structured SQLite store
(core/memory_store.py) instead of an append-only markdown file.

Migration: on first run with an empty store, an existing memory/freya_memory.md is
parsed deterministically (section headers → subjects, bullets → items) and renamed to
freya_memory.imported.md as a backup. No LLM call is needed to migrate.

Session-end extraction now asks gemini-2.5-flash-lite for a JSON array of typed
memory items plus one session summary, inserted as rows — searchable and editable
instead of appended forever.
"""

import asyncio
import json
import os
import re
from datetime import datetime

from google import genai
from google.genai import types

from core.memory_store import get_store, KINDS

MEMORY_PATH = os.path.join(os.path.dirname(__file__), '..', 'memory', 'freya_memory.md')


# ══════════════════════════════════════════════
#  ONE-TIME MARKDOWN IMPORT
# ══════════════════════════════════════════════
def _migrate_markdown_if_needed() -> None:
    store = get_store()
    if store.count() > 0 or not os.path.exists(MEMORY_PATH):
        return
    try:
        with open(MEMORY_PATH, 'r', encoding='utf-8') as f:
            text = f.read()
        section = "Imported"
        imported = 0
        for line in text.splitlines():
            line = line.strip()
            if line.startswith('#'):
                section = line.lstrip('#').strip() or section
            elif line.startswith(('-', '*')) and len(line) > 2:
                content = line[1:].strip()
                if content:
                    kind = "session_summary" if re.match(r"^\d{4}-\d{2}-\d{2}", section) else "fact"
                    store.add(kind=kind, subject=section[:80], content=content,
                              importance=2, source="markdown_import")
                    imported += 1
        os.replace(MEMORY_PATH, MEMORY_PATH.replace('.md', '.imported.md'))
        print(f"  Memory: imported {imported} items from markdown (backup kept as .imported.md).")
    except Exception as e:
        print(f"  Memory migration failed (continuing with empty store): {e}")


# ══════════════════════════════════════════════
#  READ MEMORY
# ══════════════════════════════════════════════
def load_memory() -> str:
    """The memory block injected into the system prompt."""
    _migrate_markdown_if_needed()
    content = get_store().compose_prompt()
    print("  Memory loaded." if content else "  No memories yet, starting fresh.")
    return content


# ══════════════════════════════════════════════
#  BUILD PERSONALITY + MEMORY PROMPT
# ══════════════════════════════════════════════
def build_system_prompt(base_personality: str, memory: str) -> str:
    """Inject memory into the system prompt so Freya knows about Ihan."""
    if not memory:
        return base_personality

    return f"""{base_personality}

---

Here is everything you remember about Ihan from previous sessions.
Use this naturally in conversation — don't recite it robotically,
just let it inform how you talk to him. You can save new memories with
`remember`, look things up with `recall` or `list_memories`, and remove
stale ones with `forget`:

{memory}
"""


# ══════════════════════════════════════════════
#  UPDATE MEMORY AFTER SESSION
# ══════════════════════════════════════════════
_EXTRACT_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "items": types.Schema(
            type=types.Type.ARRAY,
            items=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "kind": types.Schema(type=types.Type.STRING,
                                         description=f"One of: {', '.join(k for k in KINDS if k != 'session_summary')}"),
                    "subject": types.Schema(type=types.Type.STRING, description="Short subject, e.g. a person's name or project"),
                    "content": types.Schema(type=types.Type.STRING, description="The fact itself, one sentence"),
                    "importance": types.Schema(type=types.Type.INTEGER, description="1 (minor) to 5 (critical)"),
                    "due_at": types.Schema(type=types.Type.STRING,
                                           description="ISO datetime if this is a deadline/followup, else empty"),
                },
                required=["kind", "subject", "content"],
            ),
        ),
        "session_summary": types.Schema(type=types.Type.STRING,
                                        description="2-3 sentence summary of the session, empty if trivial"),
    },
    required=["items", "session_summary"],
)


async def update_memory(api_key: str, transcript: list[str], current_memory: str) -> None:
    """Extract structured memory items from the session transcript."""
    if not transcript or len(transcript) < 3:
        print("  Session too short to extract memories.")
        return

    print("\n  Updating Freya's memory...")
    conversation_text = "\n".join(transcript)
    today = datetime.now().strftime("%Y-%m-%d %H:%M")

    prompt = f"""Extract NEW long-term memory items from this voice-session transcript
(today: {today}). Only durable facts worth remembering across sessions: preferences,
people and their roles, ongoing projects, deadlines/follow-ups (with due_at), and
notable facts about Ihan. Skip anything already known:

KNOWN MEMORY:
{current_memory or '(empty)'}

TRANSCRIPT:
{conversation_text}"""

    max_retries = 3
    retry_delay = 35

    for attempt in range(1, max_retries + 1):
        try:
            client = genai.Client(api_key=api_key)
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None,
                lambda: client.models.generate_content(
                    model="gemini-2.5-flash-lite",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=_EXTRACT_SCHEMA,
                    ),
                ),
            )
            data = json.loads(response.text or "{}")
            store = get_store()
            added = 0
            for item in data.get("items", []):
                content = str(item.get("content", "")).strip()
                if not content:
                    continue
                store.add(
                    kind=str(item.get("kind", "fact")),
                    subject=str(item.get("subject", "General"))[:80],
                    content=content,
                    importance=int(item.get("importance", 2) or 2),
                    due_at=(str(item.get("due_at")) or None) or None,
                    source="session_extraction",
                )
                added += 1
            summary = str(data.get("session_summary", "")).strip()
            if summary:
                store.add(kind="session_summary", subject=today[:10], content=summary,
                          importance=1, source="session_extraction")
            print(f"  Memory updated: {added} items" + (" + summary." if summary else "."))
            if added or summary:
                from core.events import bus
                await bus.publish("memory_changed", {"kinds": ["fact"]})
            return

        except Exception as e:
            error_str = str(e)
            if "429" in error_str and attempt < max_retries:
                print(f"  Rate limited (attempt {attempt}/{max_retries}). Retrying in {retry_delay}s...")
                await asyncio.sleep(retry_delay)
                retry_delay *= 2
            else:
                print(f"  Memory update failed: {e}")
                return


# ══════════════════════════════════════════════
#  TRANSCRIPT COLLECTOR
# ══════════════════════════════════════════════
class TranscriptCollector:
    """Collects conversation lines during a session for memory update."""

    def __init__(self):
        self.lines: list[str] = []

    def add(self, speaker: str, text: str):
        text = text.strip()
        if text:
            self.lines.append(f"{speaker}: {text}")

    def get(self) -> list[str]:
        return self.lines

    def is_empty(self) -> bool:
        return len(self.lines) == 0
