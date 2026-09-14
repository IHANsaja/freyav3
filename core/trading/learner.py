"""The learner's trading knowledge, kept in Freya's long-term memory so lessons build over time.

Stored as one `fact` item in the structured memory store. Its first line is a plain
summary (so it also reaches Freya's system prompt through normal memory loading);
the exact profile follows after a DATA: marker.
"""
import json
from datetime import datetime, timezone

SUBJECT = "Trading knowledge profile"
LEVELS = ("complete beginner", "beginner", "developing", "intermediate", "advanced")
MAX_TOPICS = 40
MARKER = "\nDATA:"


def _default():
    return dict(level="complete beginner", understood=[], learning_now=None, struggling=[],
                notes=[], lessons=0, updated=None,
                guidance="Assume no prior trading knowledge. Explain every term in plain words.")


def _store():
    from core.memory_store import get_store
    return get_store()


def _item():
    return next((i for i in _store().list(kinds=["fact"], limit=500) if i.subject == SUBJECT), None)


def profile():
    item = _item()
    if item is None or MARKER not in item.content:
        return _default()
    try:
        data = json.loads(item.content.split(MARKER, 1)[1])
    except (ValueError, IndexError):
        return _default()
    return {**_default(), **data}


def _clean(values):
    return [str(v).strip()[:80] for v in (values or []) if str(v).strip()]


def _merge(existing, added):
    seen = {v.lower() for v in existing}
    merged = list(existing) + [v for v in added if v.lower() not in seen and not seen.add(v.lower())]
    return merged[-MAX_TOPICS:]


def update(level=None, understood=None, struggling=None, learning_now=None, note=None):
    """Merge progress into the profile and persist it. Returns the new profile."""
    data = profile()
    if level is not None:
        level = str(level).strip().lower()
        if level not in LEVELS:
            raise ValueError(f"level must be one of: {', '.join(LEVELS)}")
        data["level"] = level
    got = _clean(understood)
    data["understood"] = _merge(data["understood"], got)
    # Understanding something removes it from the struggle list.
    lowered = {v.lower() for v in got}
    data["struggling"] = _merge([v for v in data["struggling"] if v.lower() not in lowered], _clean(struggling))
    if learning_now is not None:
        data["learning_now"] = str(learning_now).strip()[:120] or None
    if note:
        data["notes"] = (data["notes"] + [str(note).strip()[:200]])[-10:]
    data["lessons"] = int(data.get("lessons") or 0) + 1
    data["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    data["guidance"] = ("Assume no prior trading knowledge. Explain every term in plain words."
                        if data["level"] == "complete beginner" and not data["understood"]
                        else "Build on what they already understand; still define any new term simply.")
    summary = (f"Trading knowledge: level {data['level']}. "
               f"Understands: {', '.join(data['understood']) or 'nothing yet'}. "
               f"Learning now: {data['learning_now'] or 'not set'}. "
               f"Struggles with: {', '.join(data['struggling']) or 'nothing noted'}.")
    content = summary + MARKER + json.dumps(data, ensure_ascii=False)
    store, item = _store(), _item()
    if item is None:
        store.add(kind="fact", subject=SUBJECT, content=content, importance=4, source="trading_lab")
    else:
        store.update(item.id, content=content, importance=4)
    return data
