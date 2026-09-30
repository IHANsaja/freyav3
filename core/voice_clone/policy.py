"""Who may make Freya speak as the user, when it needs his confirmation, and
the record of everything she said in his voice."""
import json
import os
import threading
import time
from collections import deque

from core.voice_clone import settings

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_LOG_PATH = os.path.join(_ROOT, "memory", "voice_log.jsonl")
_log_lock = threading.Lock()
_recent = deque()        # monotonic times of lines spoken as the user


def check_source(ctx) -> str | None:
    """Only the user, talking to Freya live, may use his voice. Missions,
    sub-agents and browser tasks are refused, so no page, document or
    delegated task can make her speak as him."""
    source = getattr(ctx, "source", "live") or "live"
    if source != "live":
        return ("Refused: speaking in the user's voice can only be asked for by the user himself "
                "in conversation, not by a background task.")
    return None


def approval_rule(tool: str, args: dict, config: dict) -> bool | None:
    """Registry approval_fn: consulted before the global approval settings, so
    "approvals off" cannot silence these tools."""
    from core.voice_clone.calls import state
    if tool == "answer_call":
        return True
    if tool == "speak_in_my_voice":
        if (args.get("where") or "call") == "speakers":
            return False                         # only he hears it
        mode = settings(config).get("confirm", "first_per_call")
        if mode == "every_line":
            return True
        if mode == "off_after_answer":
            return not state.is_active()
        return not (state.is_active() and state.first_line_approved)
    return None


def ui_only(args: dict) -> bool:
    """During a handled call the caller's voice comes out of the speakers, so
    only a dashboard click may approve."""
    from core.voice_clone.calls import state
    return state.is_active()


def check_text(text: str, config: dict) -> str | None:
    vc = settings(config)
    text = (text or "").strip()
    if not text:
        return "Tell me what to say."
    if len(text) > int(vc["max_chars"]):
        return f"That's too long to say in one go ({len(text)} characters; the limit is {vc['max_chars']})."
    now = time.monotonic()
    while _recent and now - _recent[0] > 60:
        _recent.popleft()
    if len(_recent) >= int(vc["max_lines_per_minute"]):
        return "That's a lot of lines in a minute; give it a moment."
    return None


def note_line():
    _recent.append(time.monotonic())


def describe(tool: str, args: dict) -> str:
    """The approval card sentence: the exact words, where they go, and that it
    is his voice."""
    from core.voice_clone.engine import LANG_NAMES, detect_lang
    if tool == "answer_call":
        from core.voice_clone.calls import APPS, normalize_app
        spec = APPS.get(normalize_app(args.get("app")))
        app = f"the {spec.name} call" if spec else "the incoming call"
        text = (args.get("message") or "").strip()
        lang = LANG_NAMES[detect_lang(text, args.get("language"))]
        said = f' and say in YOUR voice ({lang}): "{text}"' if text else ""
        extra = " (after saying it's your assistant)" if args.get("disclose") else ""
        return f"answer {app}{said}{extra}"
    text = (args.get("text") or "").strip()
    lang = detect_lang(text, args.get("language"))
    where = "on your speakers" if args.get("where") == "speakers" else "into the call"
    stand_in = " - NOT your voice, a stand-in Gemini voice" if lang != "en" else ""
    return f'say {where} in YOUR voice ({LANG_NAMES[lang]}){stand_in}: "{text}"'


def audit(**fields) -> None:
    """Append one line to memory/voice_log.jsonl (private, gitignored)."""
    try:
        from config import load_config
        if not settings(load_config()).get("audit_log", True):
            return
    except Exception:
        pass
    entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **fields}
    with _log_lock:
        try:
            os.makedirs(os.path.dirname(_LOG_PATH), exist_ok=True)
            with open(_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass


def recent_log(limit: int = 20) -> list[dict]:
    try:
        with open(_LOG_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()[-limit:]
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return list(reversed(out))
