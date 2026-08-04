"""
DuckDuckGo — Freya's search engine.

DDG over Google for three practical reasons: no API key, no consent wall to
click through on every cold profile, and no aggressive bot-interstitial that
would stop a fresh automated context dead.

Filtering
---------
SafeSearch is OFF by default (`kp=-2`), set both as a URL parameter and as the
`p` cookie so it holds across in-browser navigation. Freya is a personal
assistant on Ihan's own machine; a search layer that silently drops results is a
search layer that lies to her about what's on the web. Flip
`browser.safe_search` to true in config to put the filter back.

This module has two callers with different needs:
  • `ddg_search()` — plain HTTP, no browser, quota-free. Used by `web_search`.
  • `ddg_search_url()` — the URL for the real browser to navigate to, so the
    agent can then read and click results like a person.
"""

import html as _html
import re
import urllib.parse
import urllib.request

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# kp: -2 = SafeSearch off, -1 = moderate, 1 = strict.
_SAFE_OFF = "-2"
_SAFE_MODERATE = "-1"


def safe_param(config: dict | None) -> str:
    """`kp` value for the configured filtering level."""
    strict = bool((config or {}).get("browser", {}).get("safe_search", False))
    return _SAFE_MODERATE if strict else _SAFE_OFF


def search_cookies(config: dict | None) -> list[dict]:
    """Cookies that pin DDG's preferences for the browser context.

    Without these the setting resets the moment the agent clicks through to a
    second results page.
    """
    kp = safe_param(config)
    common = {"domain": ".duckduckgo.com", "path": "/"}
    return [
        {"name": "p", "value": kp, **common},        # SafeSearch
        {"name": "kl", "value": "wt-wt", **common},  # no region skew
        {"name": "kac", "value": "-1", **common},    # no auto-suggest interference
        {"name": "kd", "value": "-1", **common},     # don't rewrite result links
    ]


def ddg_search_url(query: str, config: dict | None = None) -> str:
    """The results URL for the real browser."""
    params = {"q": query, "kp": safe_param(config), "kl": "wt-wt", "ia": "web"}
    return "https://duckduckgo.com/?" + urllib.parse.urlencode(params)


def ddg_html_url(query: str, config: dict | None = None) -> str:
    """The no-JS results page. Plain links, no front-end — used as the fallback
    when DDG's main site decides an automated context looks like a bot."""
    params = {"q": query, "kp": safe_param(config), "kl": "wt-wt"}
    return "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode(params)


def ddg_news_url(query: str, config: dict | None = None) -> str:
    params = {"q": query, "kp": safe_param(config), "iar": "news", "ia": "news"}
    return "https://duckduckgo.com/?" + urllib.parse.urlencode(params)


# ── Headless HTTP search (no browser, no quota) ────────────────────────────
def _clean(s: str) -> str:
    return _html.unescape(re.sub(r"<[^>]+>", "", s)).strip()


def _unwrap(href: str) -> str:
    """DDG wraps results in /l/?uddg=<real-url>. Unwrap so callers get the
    destination, not a redirector."""
    if href.startswith("//"):
        href = "https:" + href
    if "uddg=" in href:
        params = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
        if params.get("uddg"):
            return params["uddg"][0]
    return href


def _fetch(url: str, data: bytes | None, config: dict | None) -> str:
    req = urllib.request.Request(
        url, data=data,
        headers={
            "User-Agent": _UA,
            "Accept-Language": "en-US,en;q=0.9",
            # The HTML endpoint reads preferences from this cookie, not just
            # the query string.
            "Cookie": f"p={safe_param(config)}; kl=wt-wt",
        },
    )
    with urllib.request.urlopen(req, timeout=12) as r:
        return r.read().decode("utf-8", "replace")


def ddg_search(query: str, n: int = 6, config: dict | None = None) -> list[dict]:
    """Search without launching a browser. Returns [{title, url, snippet}].

    Tries the HTML endpoint, then the lite one — DDG rotates which of the two
    is friendly to non-browser clients, and a search that returns nothing looks
    to Freya exactly like a web with no answer on it.
    """
    payload = urllib.parse.urlencode({"q": query, "kp": safe_param(config), "kl": "wt-wt"}).encode()

    for endpoint, pattern in (
        ("https://html.duckduckgo.com/html/", r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>'),
        ("https://lite.duckduckgo.com/lite/", r'class="result-link"[^>]*href="([^"]+)"[^>]*>(.*?)</a>'),
    ):
        try:
            page = _fetch(endpoint, payload, config)
        except Exception:
            continue

        results: list[dict] = []
        for m in re.finditer(pattern, page, re.S):
            url = _unwrap(m.group(1))
            if not url.startswith("http"):
                continue
            # Snippet: the nearest following snippet block, if there is one.
            tail = page[m.end(): m.end() + 2500]
            sn = re.search(r'class="result__snippet"[^>]*>(.*?)</a>', tail, re.S) or \
                 re.search(r'class="result-snippet"[^>]*>(.*?)</td>', tail, re.S)
            results.append({
                "title": _clean(m.group(2)),
                "url": url,
                "snippet": _clean(sn.group(1))[:400] if sn else "",
            })
            if len(results) >= n:
                break
        if results:
            return results
    return []


def ddg_news(query: str, n: int = 6, config: dict | None = None) -> list[dict]:
    """News results via DDG's JSON news endpoint, SafeSearch honoured."""
    params = {"q": query, "kp": safe_param(config), "kl": "wt-wt",
              "noamp": "1", "o": "json"}
    url = "https://duckduckgo.com/news.js?" + urllib.parse.urlencode(params)
    try:
        import json
        raw = _fetch(url, None, config)
        data = json.loads(raw)
    except Exception:
        return []
    out = []
    for item in (data.get("results") or [])[:n]:
        out.append({
            "title": _clean(item.get("title", "")),
            "url": item.get("url", ""),
            "snippet": _clean(item.get("excerpt", ""))[:400],
            "source": item.get("source", ""),
        })
    return out
