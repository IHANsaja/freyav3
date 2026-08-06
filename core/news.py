"""
Real news — Freya reads headlines aloud AND projects them onto the dashboard as dynamic cards.

When the user asks for news, this:
  1. Pulls the Google News RSS feed (no API key) and returns the top headlines as text for
     Freya to speak.
  2. Emits a structured `news` event to the UI immediately so the dashboard can scatter the
     headlines as dynamic projections around the AI globe (with live animated figures).
  3. Kicks off a BACKGROUND scrape of each article's og:image and emits `news_image` events as
     they resolve — so images appear over the scene a moment later without delaying her speech.
"""

import asyncio
import hashlib
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from core.registry import register, tool, OBJ, P, STR

_UA = {"User-Agent": "Mozilla/5.0 (FreyaAI/3.0)"}
_TOP = "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en"
_SEARCH = "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"


def _hid(title: str) -> int:
    """Stable id for a headline so the UI can match an incoming image to its card."""
    return int(hashlib.md5(title.encode("utf-8")).hexdigest()[:8], 16)


def _domain(url: str) -> str:
    try:
        return urllib.parse.urlparse(url).netloc
    except Exception:
        return ""


def _fetch_items(url: str, limit: int = 5) -> list[dict]:
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=8) as resp:
        root = ET.fromstring(resp.read())
    items = []
    for it in root.findall(".//item")[:limit]:
        title = (it.findtext("title") or "").strip()
        if not title:
            continue
        headline = title.rsplit(" - ", 1)[0] if " - " in title else title
        source = title.rsplit(" - ", 1)[1] if " - " in title else ""
        # Source homepage -> a guaranteed logo image (shown instantly in the scene,
        # before/instead of a scraped article photo).
        src_el = it.find("source")
        dom = _domain(src_el.get("url")) if src_el is not None and src_el.get("url") else ""
        logo = f"https://www.google.com/s2/favicons?domain={dom}&sz=128" if dom else None
        items.append({"title": headline, "source": source,
                      "link": (it.findtext("link") or "").strip(), "logo": logo})
    return items


def _fetch_headlines(url: str, limit: int = 5) -> list[str]:
    """Kept for the scheduler's morning briefing."""
    return [i["title"] for i in _fetch_items(url, limit)]


def _format(headlines: list[str], label: str) -> str:
    if not headlines:
        return f"I couldn't pull any {label} right now — the news feed didn't respond."
    lines = "; ".join(f"{i+1}. {h}" for i, h in enumerate(headlines))
    return (f"Here are the top {label} right now: {lines}. "
            "Read these to the user conversationally — don't just list numbers robotically.")


def _og_image(link: str, timeout: int = 5) -> str | None:
    """Lightweight web scrape: follow the article link and grab its og:image."""
    try:
        req = urllib.request.Request(link, headers=_UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            html = r.read(220_000).decode("utf-8", "replace")
    except Exception:
        return None
    for pat in (r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
                r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)'):
        m = re.search(pat, html, re.I)
        if m and m.group(1).startswith("http"):
            return m.group(1)
    return None


async def _scrape_images(items: list[dict], ctx):
    """Background: find each headline's photo, DOWNLOAD it server-side, and project it onto
    the scene as a data URI (so it always renders — no hotlink/CORS failures).

    Google News RSS links point at news.google.com interstitial pages (JS-only redirect,
    no og:image), so scraping the feed link directly almost never yields a photo. Fallback:
    web-search the headline (DuckDuckGo returns the real publisher URL) and take the top
    result's og:image. Items run concurrently (capped) so all cards fill in within seconds."""
    loop = asyncio.get_running_loop()
    from core.web import download_image_raw, _find_image_url
    sem = asyncio.Semaphore(2)  # polite to DDG; keeps total fill-in fast

    async def one(it: dict):
        try:
            async with sem:
                img_url = None
                link = it.get("link") or ""
                if link and "news.google.com" not in link:
                    img_url = await loop.run_in_executor(None, _og_image, link)
                if not img_url:
                    query = f"{it['title']} {it.get('source', '')}".strip()
                    img_url = await loop.run_in_executor(None, _find_image_url, query)
                if not img_url:
                    return
                raw = await loop.run_in_executor(
                    None, lambda u=img_url: download_image_raw(u, link or None))
                if raw:
                    await ctx.emit("news_image",
                                   {"id": _hid(it["title"]), "image": "data:image/jpeg;base64," + raw})
        except Exception:
            pass

    await asyncio.gather(*(one(it) for it in items if it.get("title")))


async def _emit_and_speak(items: list[dict], label: str, ctx) -> str:
    spoken = _format([i["title"] for i in items], label)
    if items and ctx is not None:
        try:
            await ctx.emit("news", {"items": [
                {"id": _hid(i["title"]), "title": i["title"], "source": i["source"],
                 "image": None, "logo": i.get("logo")}
                for i in items
            ]})
            asyncio.create_task(_scrape_images(items, ctx))
        except Exception:
            pass
    return spoken


# ── Tools (async so they can emit UI events while staying fast for voice) ──
@tool(
    "get_world_news",
    "Fetch the latest TOP world/global news, read the headlines aloud, AND display them with "
    "images directly on Freya's dashboard scene (no browser). This is the tool for ANY news "
    "request — including 'show me the news images', 'show news', 'what's happening around the "
    "world'. NEVER open a browser for news; this shows everything in the UI.",
    OBJ(),
)
async def get_world_news(args: dict, ctx) -> str:
    loop = asyncio.get_running_loop()
    try:
        items = await loop.run_in_executor(None, _fetch_items, _TOP, 5)
    except Exception as e:
        return f"Couldn't fetch world news: {e}"
    return await _emit_and_speak(items, "world headlines", ctx)


async def _get_news(args: dict, ctx) -> str:
    topic = (args.get("topic") or "world").strip()
    if topic.lower() in ("world", "global", ""):
        return await get_world_news(args, ctx)
    loop = asyncio.get_running_loop()
    try:
        url = _SEARCH.format(q=urllib.parse.quote(topic))
        items = await loop.run_in_executor(None, _fetch_items, url, 5)
    except Exception as e:
        return f"Couldn't fetch {topic} news: {e}"
    return await _emit_and_speak(items, f"{topic} headlines", ctx)


# Handler-only override — declaration already lives in model.py's static list.
register("get_news", _get_news)
