"""
System One (TypeSafe Jev) — fast typed decisions next to Gemini.

Jev answers yes/no (Noul), pick-one (Choice) and rate-on-a-scale (Score)
questions in ~70-500 ms, with calibrated probabilities, and cannot generate
text. So it never replaces a Gemini call outright: every caller asks Jev
first and falls back to the path it had before (Gemini, or a heuristic) when
Jev is off, unreachable, or not confident enough.

Every helper returns None instead of raising. A failure also opens a short
circuit breaker so an outage costs one timeout, not one per turn.

On/off: the key decides. TYPESAFE_API_KEY in .env → Jev is used; no key →
Gemini only (Jev is early-access, so most installs won't have one).

Tuning (config/freya_config.json), all optional:
    "system_one": {
        "model": "jev-latest",
        "timeout_s": 2.5,
        "features": {"tool_routing": true, "mission_verify": true, ...}
    }
A feature set to false stays on Gemini even with a key.
"""

import asyncio
import os
import time

import httpx

API_URL = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-latest"
_BREAKER_S = 60.0  # after a failure, skip Jev entirely for this long

_clients: dict[int, httpx.AsyncClient] = {}
_down_until = 0.0


def _cfg(config: dict | None) -> dict:
    return (config or {}).get("system_one") or {}


def available() -> bool:
    """Jev is an early-access API: the key is the switch. With a
    TYPESAFE_API_KEY Freya uses Jev; without one she runs on Gemini alone."""
    return bool((os.getenv("TYPESAFE_API_KEY") or "").strip())


def enabled(config: dict | None, feature: str) -> bool:
    """Is Jev keyed, healthy, and allowed for this feature?"""
    if not available():
        return False
    if time.time() < _down_until:
        return False
    return bool((_cfg(config).get("features") or {}).get(feature, True))


def describe_status() -> str:
    return ("Jev: on (TYPESAFE_API_KEY found) — fast decisions via Jev, Gemini as fallback."
            if available() else
            "Jev: off (no TYPESAFE_API_KEY) — running on Gemini only.")


def setting(config: dict | None, feature: str, key: str, default):
    """Per-feature tuning, e.g. system_one.mission_verify.pass_at."""
    return (_cfg(config).get(feature) or {}).get(key, default)


def _client() -> httpx.AsyncClient:
    # Missions run on the background loop and the voice session on the main
    # one; an AsyncClient's connection pool belongs to a single loop.
    loop = asyncio.get_running_loop()
    client = _clients.get(id(loop))
    if client is None or client.is_closed:
        client = httpx.AsyncClient()
        _clients[id(loop)] = client
    return client


async def ask(state, questions: dict, config: dict | None, feature: str) -> dict | None:
    """One request, many questions. Returns {question_id: answer} or None."""
    global _down_until
    if not enabled(config, feature):
        return None
    c = _cfg(config)
    started = time.perf_counter()
    try:
        resp = await _client().post(
            API_URL,
            headers={"Authorization": f"Bearer {os.getenv('TYPESAFE_API_KEY')}"},
            json={"state": state, "model": c.get("model", DEFAULT_MODEL), "questions": questions},
            timeout=float(c.get("timeout_s", 2.5)),
        )
        if resp.status_code == 422:
            # Our request was malformed — a bug to fix, not an outage.
            print(f"  [jev] {feature}: rejected request: {resp.text[:200]}")
            return None
        resp.raise_for_status()
        answers = resp.json().get("answers") or {}
    except Exception as e:
        _down_until = time.time() + _BREAKER_S
        print(f"  [jev] {feature}: unavailable ({type(e).__name__}); "
              f"falling back for {int(_BREAKER_S)}s")
        return None
    if c.get("log", False):
        print(f"  [jev] {feature}: {(time.perf_counter() - started) * 1000:.0f} ms")
    return answers


async def noul(state, instructions, config, feature: str, criteria: dict | None = None) -> float | None:
    """Probability (0-1) that the answer is yes."""
    q = {"type": "noul", "instructions": instructions}
    if criteria:
        q["criteria"] = criteria
    answers = await ask(state, {"q": q}, config, feature)
    try:
        return float(answers["q"]["noul"])
    except (TypeError, KeyError, ValueError):
        return None


async def choice(state, instructions, options: dict, config, feature: str) -> dict | None:
    """{"choice", "probabilities", "confidence"} over `options` (option -> description|None)."""
    answers = await ask(state, {"q": {"type": "choice", "instructions": instructions,
                                      "criteria": options}}, config, feature)
    try:
        a = answers["q"]
        return {"choice": a["choice"], "probabilities": a["probabilities"],
                "confidence": float(a["confidence"])}
    except (TypeError, KeyError, ValueError):
        return None


_IMPORTANCE_LEVELS = [
    "Trivia: a passing detail nobody will need again",
    "Minor: mildly useful background",
    "Useful: a real preference, fact or ongoing thing worth keeping",
    "Important: shapes how to help him, or has a date attached",
    "Critical: health, safety, money, a hard deadline, or something he explicitly asked to keep",
]


async def memory_importance(items: list[str], config, feature: str = "memory_triage") -> list[int | None]:
    """1-5 importance per memory item, all in one request; None where unsure."""
    if not items:
        return []
    questions = {
        f"i{n}": {"type": "score",
                  "instructions": {"memory_item": text[:500],
                                   "question": "How important is `memory_item` for a personal "
                                               "assistant to remember long term?"},
                  "criteria": _IMPORTANCE_LEVELS}
        for n, text in enumerate(items)
    }
    answers = await ask("Long-term memory triage for a personal voice assistant.",
                        questions, config, feature) or {}
    min_conf = float(setting(config, feature, "min_confidence", 0.5))
    out: list[int | None] = []
    for n in range(len(items)):
        a = answers.get(f"i{n}") or {}
        try:
            out.append(round(float(a["score"])) + 1 if float(a["confidence"]) >= min_conf else None)
        except (KeyError, TypeError, ValueError):
            out.append(None)
    return out


async def score(state, instructions, levels: list, config, feature: str) -> dict | None:
    """{"score", "confidence"}; score is 0-based across `levels` and may fall between them."""
    answers = await ask(state, {"q": {"type": "score", "instructions": instructions,
                                      "criteria": levels}}, config, feature)
    try:
        a = answers["q"]
        return {"score": float(a["score"]), "confidence": float(a["confidence"])}
    except (TypeError, KeyError, ValueError):
        return None
