import os
import asyncio
from datetime import datetime
from google import genai
from google.genai import types

MEMORY_PATH = os.path.join(os.path.dirname(__file__), '..', 'memory', 'freya_memory.md')


# ══════════════════════════════════════════════
#  READ MEMORY
# ══════════════════════════════════════════════
def load_memory() -> str:
    """Read the memory markdown file and return its contents as a string."""
    try:
        with open(MEMORY_PATH, 'r', encoding='utf-8') as f:
            content = f.read().strip()
        print("  Memory loaded.")
        return content
    except FileNotFoundError:
        print("  No memory file found, starting fresh.")
        return ""


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
just let it inform how you talk to him:

{memory}
"""


# ══════════════════════════════════════════════
#  UPDATE MEMORY AFTER SESSION
# ══════════════════════════════════════════════
async def update_memory(api_key: str, transcript: list[str], current_memory: str) -> None:
    """
    After a session ends, ask Gemini to extract any new facts from the
    conversation transcript and append them to the memory file.
    """
    if not transcript:
        print("  No transcript to update memory from.")
        return

    if len(transcript) < 3:
        print("  Session too short to extract memories.")
        return

    print("\n  Updating Freya's memory...")

    # Build the conversation text
    conversation_text = "\n".join(transcript)
    today = datetime.now().strftime("%Y-%m-%d")

    prompt = f"""You are a memory extraction assistant for Freya, an AI voice assistant.

Here is the existing memory file:
{current_memory}

Here is the conversation transcript from today's session ({today}):
{conversation_text}

Your job:
1. Extract any NEW facts, preferences, or important things Ihan mentioned that are NOT already in the memory file.
2. Write a short session summary (2-3 bullet points max) for today.
3. Return ONLY the new content to append to the memory file in this exact format:

## Things Ihan has told me (new)
- [new fact if any, skip this section if nothing new]

### {today}
- [session bullet 1]
- [session bullet 2]

If there is nothing new to add, return exactly: NOTHING_NEW
Do not return the full memory file. Only return the new content to append."""

    max_retries = 3
    retry_delay = 35  # seconds — API suggests ~31s

    for attempt in range(1, max_retries + 1):
        try:
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model="gemini-2.5-flash-lite",
                contents=prompt
            )

            result = response.text.strip()

            if result == "NOTHING_NEW" or not result:
                print("  Nothing new to add to memory.")
                return

            # Append new content to memory file
            with open(MEMORY_PATH, 'a', encoding='utf-8') as f:
                f.write(f"\n{result}\n")

            print("  Memory updated successfully.")
            return

        except Exception as e:
            error_str = str(e)
            if "429" in error_str and attempt < max_retries:
                print(f"  Rate limited (attempt {attempt}/{max_retries}). Retrying in {retry_delay}s...")
                await asyncio.sleep(retry_delay)
                retry_delay *= 2  # exponential backoff
            else:
                print(f"  Memory update failed: {e}")


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