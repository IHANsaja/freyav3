"""
Real news — Freya actually reads the headlines aloud instead of opening a browser tab.

The old `get_news` in core/tools.py just popped open Google News in the browser. When Ihan
asks "what's happening around the world?", Freya should *speak* the news. This module pulls
the Google News RSS feed (no API key, no quota) and returns the top headlines as plain text
that the live model narrates.
"""

import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from core.registry import register, tool, OBJ, P, STR, INT

_UA = {"User-Agent": "Mozilla/5.0 (FreyaAI/3.0)"}
_TOP = "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en"
_SEARCH = "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"


def _fetch_headlines(url: str, limit: int = 5) -> list[str]:
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=8) as resp:
        raw = resp.read()
    root = ET.fromstring(raw)
    items = root.findall(".//item")
    headlines = []
    for item in items[:limit]:
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        # Google formats titles as "Headline - Source"; keep the headline part.
        headline = title.rsplit(" - ", 1)[0] if " - " in title else title
        headlines.append(headline)
    return headlines


def _format(headlines: list[str], label: str) -> str:
    if not headlines:
        return f"I couldn't pull any {label} right now — the news feed didn't respond."
    lines = "; ".join(f"{i+1}. {h}" for i, h in enumerate(headlines))
    return (
        f"Here are the top {label} right now: {lines}. "
        "Read these to Ihan conversationally — don't just list numbers robotically."
    )


# ── Tools ──────────────────────────────────────────────────────────────────
@tool(
    "get_world_news",
    "Fetch the latest TOP world/global news headlines and read them aloud. Use when Ihan asks "
    "'what's happening around the world', 'what's the news', 'any news today', etc.",
    OBJ(),
)
def get_world_news(args: dict, ctx) -> str:
    try:
        return _format(_fetch_headlines(_TOP, 5), "world headlines")
    except Exception as e:
        return f"Couldn't fetch world news: {e}"


def _get_news(args: dict, ctx) -> str:
    """Improved get_news: returns spoken headlines for a topic (overrides the
    browser-opening version in core/tools.py)."""
    topic = (args.get("topic") or "world").strip()
    if topic.lower() in ("world", "global", ""):
        return get_world_news(args, ctx)
    try:
        url = _SEARCH.format(q=urllib.parse.quote(topic))
        return _format(_fetch_headlines(url, 5), f"{topic} headlines")
    except Exception as e:
        return f"Couldn't fetch {topic} news: {e}"


# Handler-only override — the declaration already lives in model.py's static list.
register("get_news", _get_news)
