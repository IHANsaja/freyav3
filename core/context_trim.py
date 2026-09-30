"""Shrinking what a background agent re-sends on every step.

Each request carries the whole history, and Gemini's tokens-per-minute limit
counts all of it as input. Only our own material is ever shortened here - tool
results and page snapshots. The model's turns go back exactly as received,
which stateless function calling requires (their thought signatures).
"""
from google.genai import types

TRIM_MARK = " ...[older tool result trimmed to stay within the token budget]"
PAGE_TAG = "CURRENT PAGE:\n"
STALE_PAGE = ("[Earlier page view removed to save tokens; the page has changed since and "
              "its element numbers are no longer valid.]")


def _is_result_turn(content) -> bool:
    return any(getattr(p, "function_response", None) for p in (content.parts or []))


def compact_results(contents: list, keep_recent: int, head_chars: int) -> int:
    """Cut the text of every tool result except the newest `keep_recent`
    result turns. Idempotent. Returns the number of characters removed."""
    turns = [c for c in contents if _is_result_turn(c)]
    removed = 0
    for content in turns[:max(0, len(turns) - keep_recent)]:
        parts = []
        for part in content.parts:
            fr = getattr(part, "function_response", None)
            response = (fr.response or {}) if fr else {}
            key = "result" if "result" in response else "error" if "error" in response else None
            text = str(response.get(key, "")) if key else ""
            if fr is None or key is None or text.endswith(TRIM_MARK) or len(text) <= head_chars:
                parts.append(part)
                continue
            removed += len(text) - head_chars
            parts.append(types.Part(function_response=types.FunctionResponse(
                id=getattr(fr, "id", None), name=fr.name,
                response={key: text[:head_chars] + TRIM_MARK})))
        content.parts = parts
    return removed


def drop_stale_pages(contents: list) -> int:
    """Replace every page snapshot but the newest with a one-line note that
    keeps its URL and title. Returns the number of characters removed."""
    removed = 0
    snapshots = [(c, i) for c in contents for i, p in enumerate(c.parts or [])
                 if (getattr(p, "text", None) or "").startswith(PAGE_TAG)]
    for content, index in snapshots[:-1]:
        text = content.parts[index].text
        header = " | ".join(line for line in text[len(PAGE_TAG):].splitlines()[:2] if line)
        note = f"{STALE_PAGE} (was: {header})" if header else STALE_PAGE
        removed += max(0, len(text) - len(note))
        parts = list(content.parts)
        parts[index] = types.Part(text=note)
        content.parts = parts
    return removed
