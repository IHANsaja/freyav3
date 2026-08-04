"""
Web search & fetch — Freya navigates the live web herself and grows her knowledge base.

Unlike the real browser (core/browser — drives Chromium via an LLM, one API call per step →
burns quota), these tools are QUOTA-FREE: they just do plain HTTP and hand the raw results to
the live voice model, which reads them. Perfect for "look something up", "what's the latest on
X", checking a current fact/date, etc. Search itself is shared with the browser stack, so both
paths use DuckDuckGo with the same filtering settings.

  • web_search(query)  — DuckDuckGo results (title + snippet + source), no API key.
  • web_fetch(url)     — open a page and return its readable text.

Both can save what they find into Freya's semantic knowledge base (core/rag_memory), so she can
`recall` it in future sessions — i.e. she updates her own knowledge.
"""

import asyncio
import base64
import html as _html
import re
import urllib.parse
import urllib.request
from io import BytesIO

from core.registry import tool, OBJ, P, STR, BOOL

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) FreyaAI/3.0"}


def _domain(url: str) -> str:
    try:
        return urllib.parse.urlparse(url).netloc
    except Exception:
        return ""


def _clean(s: str) -> str:
    return _html.unescape(re.sub(r"<[^>]+>", "", s)).strip()


def _ddg_search(query: str, n: int = 5, config: dict | None = None) -> list[dict]:
    """DuckDuckGo results — now delegated to core/browser/search.py.

    That module is the single place search behaviour lives, so the quota-free
    HTTP path here and the real-browser path the agent drives return the same
    results with the same filtering settings (SafeSearch off unless
    `browser.safe_search` is turned on). This wrapper stays because
    core/news.py and _find_image_url call it by name.
    """
    from core.browser.search import ddg_search
    return ddg_search(query, n, config)


def _extract_text(url: str, max_chars: int = 4000) -> str:
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=12) as r:
        raw = r.read(900_000)
    page = raw.decode("utf-8", "replace")
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(page, "html.parser")
        for t in soup(["script", "style", "nav", "footer", "header", "noscript", "form"]):
            t.decompose()
        text = " ".join(soup.get_text(" ").split())
    except Exception:
        page = re.sub(r"<(script|style)[\s\S]*?</\1>", " ", page, flags=re.I)
        text = " ".join(_html.unescape(re.sub(r"<[^>]+>", " ", page)).split())
    return text[:max_chars]


def download_image_raw(url: str, referer: str | None = None,
                       max_w: int = 800, quality: int = 72) -> str | None:
    """Download an image and return RAW base64 JPEG (no data: prefix).

    Downloading server-side + re-encoding bypasses the hotlink/CORS/referrer blocks that make
    remote <img src> tags fail in the browser, so the image always renders on the canvas.
    """
    try:
        headers = dict(_UA)
        if referer:
            headers["Referer"] = referer
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=12) as r:
            if not r.headers.get_content_type().startswith("image"):
                return None
            data = r.read(8_000_000)
        from PIL import Image
        img = Image.open(BytesIO(data)).convert("RGB")
        if img.width > max_w:
            img = img.resize((max_w, int(img.height * max_w / img.width)), Image.LANCZOS)
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        return base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception:
        return None


def _find_image_url(query: str) -> str | None:
    """Find a representative image for a query: og:image of the top web result(s)."""
    try:
        from core.news import _og_image
        for r in _ddg_search(query, 3):
            img = _og_image(r["url"])
            if img:
                return img
    except Exception:
        pass
    return None


def _save_to_kb(label: str, docs: list[str]) -> bool:
    """Add findings to the semantic knowledge base so `recall` can retrieve them later."""
    try:
        from core.rag_memory import _add
        _add([d for d in docs if d.strip()], f"web:{label[:60]}")
        return True
    except Exception as e:
        print(f"  [web] knowledge-base save skipped: {e}")
        return False


# ══════════════════════════════════════════════
#  TOOLS
# ══════════════════════════════════════════════
@tool(
    "web_search",
    "Search the LIVE web and read the top results yourself — fast and quota-free (no browser). "
    "Use this for quick lookups: 'search the web for X', 'look something up', 'what's the latest "
    "on X', checking a current fact, date, price, or definition. By default it also saves what it "
    "finds to your knowledge base so you remember it. Prefer this over browser_task for simple "
    "information lookups.",
    OBJ({"query": P(STR, "What to search for"),
         "save": P(BOOL, "Save the findings to your knowledge base (default true)")}, ["query"]),
)
def web_search(args, ctx) -> str:
    query = (args.get("query") or "").strip()
    if not query:
        return "What should I search the web for?"
    try:
        results = _ddg_search(query, 5, ctx.config)
    except Exception as e:
        return f"Web search failed: {e}"
    if not results:
        return f"I couldn't find web results for '{query}'."
    lines = [f"{i+1}. {r['title']} — {r['snippet'][:180]} ({_domain(r['url'])})"
             for i, r in enumerate(results)]
    saved = ""
    if args.get("save", True):
        if _save_to_kb(query, [f"{r['title']}. {r['snippet']} (source: {r['url']})" for r in results]):
            saved = " I've saved this to my knowledge base."
    return (f"Top web results for '{query}':\n" + "\n".join(lines) +
            f"\nSummarize these for Ihan and cite sources naturally.{saved}")


@tool(
    "show_image",
    "Download an image and display it on the dashboard canvas. Provide a direct image URL, or a "
    "search query to find a relevant image (e.g. for a news story, place, person, or topic). "
    "Use it to illustrate what you're talking about — especially alongside news.",
    OBJ({"query": P(STR, "What to show, e.g. 'Eiffel Tower at night' or a news subject"),
         "url": P(STR, "A direct image URL (optional; use instead of query)"),
         "label": P(STR, "Short caption shown on the card")}),
)
async def show_image(args, ctx) -> str:
    loop = asyncio.get_running_loop()
    label = (args.get("label") or args.get("query") or "Image").strip()
    url = (args.get("url") or "").strip()
    if not url:
        q = (args.get("query") or "").strip()
        if not q:
            return "Tell me what image to show (a query or a URL)."
        url = await loop.run_in_executor(None, _find_image_url, q)
    if not url:
        return f"I couldn't find an image for that."
    raw = await loop.run_in_executor(None, lambda: download_image_raw(url, url))
    if not raw:
        return "I found an image but couldn't download it."
    await ctx.emit("image", {"data": raw, "label": label})
    return f"There — I've put an image of {label} on the canvas."


@tool(
    "web_fetch",
    "Open a specific web page by URL and read its main text — quota-free, no browser. Use to go "
    "deeper on a result from web_search. Can save the page to your knowledge base.",
    OBJ({"url": P(STR, "The full URL to open and read"),
         "save": P(BOOL, "Save the page content to your knowledge base")}, ["url"]),
)
def web_fetch(args, ctx) -> str:
    url = (args.get("url") or "").strip()
    if not url.startswith("http"):
        return "Give me a full URL starting with http."
    try:
        text = _extract_text(url)
    except Exception as e:
        return f"Couldn't open that page: {e}"
    if not text:
        return "That page had no readable text."
    saved = ""
    if args.get("save"):
        if _save_to_kb(url, [text]):
            saved = " Saved to my knowledge base."
    return f"From {_domain(url)}: {text[:2500]}{saved}"
