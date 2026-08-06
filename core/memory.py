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
from core.user_identity import get_preferred_name, get_user_name, get_user_profile

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
def load_memory(config: dict | None = None) -> str:
    """The memory block injected into the system prompt."""
    _migrate_markdown_if_needed()
    store = get_store()

    removed = store.dedupe() + store.purge_trivial_day_summaries()
    if removed:
        print(f"  Memory: deactivated {removed} duplicate/empty item(s).")

    max_items = int(((config or {}).get("memory", {}) or {}).get("prompt_max_items", 20))
    content = store.compose_prompt(max_items=max_items)
    print("  Memory loaded." if content else "  No memories yet, starting fresh.")
    return content


# ══════════════════════════════════════════════
#  BUILD PERSONALITY + MEMORY PROMPT
# ══════════════════════════════════════════════
def _identity_block() -> str:
    """Who the user is — sourced only from memory/MEMORY.md."""
    profile = get_user_profile()
    if not profile:
        return ("\n---\n\nYou do not know the user's name, so use no name at all — address "
                "them as \"you\" rather than inventing one or reaching for a pet name. Never "
                "guess a name from the Windows account folder, file paths or anything else on "
                "this machine. If they tell you their name, ask them to add it to "
                "memory/MEMORY.md — that file is the only place you take it from.\n")

    name = get_user_name()
    spoken = get_preferred_name()
    intro = f"The user's name is {name}. " if name else ""

    # Knowing the name was never the problem — using it was. Without this she
    # fell back on the personality's flirty register and called him "sweetheart",
    # which is the opposite of the closeness a real name carries.
    usage = ""
    if spoken:
        usage = (
            f"\nCall him {spoken}. Use his name out loud the way someone close to him "
            f"would: greeting him, reassuring him, landing a point, catching his attention, "
            f"coming back to him after a gap. Not in every sentence — a name in every line "
            f"sounds like a salesman, and most replies should carry none at all. Never "
            f"replace it with a pet name like 'sweetheart', 'honey' or 'darling'; his name "
            f"is the warmer word.\n"
        )

    return f"""
---

{intro}This is their profile, from memory/MEMORY.md. It is the ONLY source for
their name and identity — never infer a name from the Windows account folder,
file paths, or anything else on this machine, and never overwrite it from
conversation. If they want it changed, they edit that file:

{profile}
{usage}"""


def _day_block() -> str:
    """Today's rolling context. Rebuilt on every session (re)connect, so a
    reconnect after midnight picks up the rotated day automatically."""
    try:
        from core.day_context import compose_prompt as day_prompt
        block = day_prompt()
    except Exception as e:
        print(f"  Day context unavailable: {e}")
        return ""
    return f"\n---\n\n{block}\n" if block else ""


def build_system_prompt(base_personality: str, memory: str) -> str:
    """Inject identity (MEMORY.md) + day context + session memory into the prompt."""
    identity = _identity_block()
    day = _day_block()
    if not memory:
        return base_personality + "\n" + identity + day

    return f"""{base_personality}
{identity}{day}
---

Here is everything you remember about the user from previous sessions.
Use this naturally in conversation — don't recite it robotically,
just let it inform how you talk to them. You can save new memories with
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
notable facts about the user. Skip anything already known.

Never extract the user's name, nickname, or how to address them — that is owned by
memory/MEMORY.md and must not be stored here:

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
