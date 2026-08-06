"""
The hands — one real Chromium window that Freya drives like a person would.

Design decisions worth knowing
------------------------------
**One browser, one thread, one loop.** Everything browser-related runs on a
single dedicated OS thread with its own event loop (`BrowserLoop`). Two reasons.
First, a persistent profile directory can only be opened by one Chromium at a
time — concurrent jobs on separate loops would fight over the lock. Second, and
the reason the old browser-use integration already did this: CDP screenshot and
DOM work stalls for many seconds under load, and if that shared a loop with the
live voice session it would starve the mic and speaker coroutines. Freya's voice
must never wait on a web page.

**A persistent profile.** Real people have a browser with history, cookies and
sessions in it. A fresh incognito context on every task means logging in again
every time, and looks like exactly what it is.

**Actions go through the motion layer.** Nothing here calls `page.click()`. A
click is: scroll the target into view, arc the cursor to it, settle, press,
release. That is both what makes it human and what makes it correct — clicking
an element the user cannot see is how automation ends up hitting overlays.
"""

import asyncio
import base64
import os
import random
import threading

from core.browser import human
from core.browser.perception import PageView, perceive
from core.browser.search import ddg_html_url, ddg_search_url, search_cookies

PROFILE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "memory", "browser_profile")

# Chromium's own automation tells, removed. `--enable-automation` is what puts
# the "controlled by automated software" infobar up and flips navigator.webdriver.
_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-features=IsolateOrigins,site-per-process,SafeBrowsing",
    "--no-default-browser-check",
    "--no-first-run",
    "--disable-popup-blocking",
    "--disable-notifications",
    "--start-maximized",
]

# Removes the JS-visible traces of an automated context. Injected before any
# page script runs, so a fingerprinting script sees a normal browser.
_STEALTH_JS = r"""
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
Object.defineProperty(navigator, 'plugins', {
  get: () => [1, 2, 3, 4, 5].map(i => ({name: 'Plugin ' + i, filename: 'p' + i}))
});
window.chrome = window.chrome || {runtime: {}, loadTimes: () => {}, csi: () => {}};
const _query = window.navigator.permissions && window.navigator.permissions.query;
if (_query) {
  window.navigator.permissions.query = (p) => (
    p && p.name === 'notifications'
      ? Promise.resolve({state: Notification.permission})
      : _query.call(window.navigator.permissions, p)
  );
}
Object.defineProperty(navigator, 'hardwareConcurrency', {get: () => 8});
Object.defineProperty(navigator, 'deviceMemory', {get: () => 8});
"""

# Consent-banner buttons we may press without asking. Reject-only, deliberately:
# an autonomous agent should never be the thing that accepts tracking on the user's
# behalf. If only an "Accept all" is on offer, the banner is left standing and
# the agent has to reason about it.
_CONSENT_REJECT = [
    "reject all", "reject non-essential", "decline all", "decline",
    "only necessary", "necessary only", "essential only",
    "only essential cookies", "refuse all", "continue without accepting",
]


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _looks_blocked(view: PageView) -> bool:
    """True when a results page is actually an anti-bot interstitial."""
    if "static-pages/418" in view.url or "/anomaly" in view.url:
        return True
    lowered = view.text[:600].lower()
    markers = ("unfortunately, bots use duckduckgo", "our systems have detected unusual traffic",
               "verify you are a human", "are you a robot", "error getting results",
               "anonymized error code")
    if any(m in lowered for m in markers):
        return True
    # Structural check, and the one that actually catches it: DDG's soft block
    # is a 200 with a near-empty body and no outbound links. Observed on the
    # HTML endpoint under headless, where the text markers alone missed it.
    return not _has_results(view)


def _has_results(view: PageView) -> bool:
    """Does this look like a results page with somewhere to click?"""
    return any(
        e.href.startswith("http") and "duckduckgo.com" not in e.href
        for e in view.elements
    )


class HumanBrowser:
    """A single Chromium window, driven through the motion layer."""

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self._bcfg = self.config.get("browser", {})
        self._pw = None
        self.context = None
        self.page = None
        self.cursor: human.Cursor | None = None
        self.view = PageView()
        self._lock = asyncio.Lock()   # one action at a time — she has one mouse

    # ── lifecycle ──────────────────────────────────────────────────────────
    async def start(self):
        if self.context is not None:
            return
        from playwright.async_api import async_playwright

        width = int(self._bcfg.get("viewport_width", 1440))
        height = int(self._bcfg.get("viewport_height", 900))
        os.makedirs(PROFILE_DIR, exist_ok=True)

        self._pw = await async_playwright().start()
        self.context = await self._pw.chromium.launch_persistent_context(
            user_data_dir=os.path.abspath(PROFILE_DIR),
            headless=bool(self._bcfg.get("headless", False)),
            args=_LAUNCH_ARGS,
            viewport={"width": width, "height": height},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            locale=self._bcfg.get("locale", "en-US"),
            timezone_id=self._bcfg.get("timezone", "Asia/Colombo"),
            # A cert warning is a wall, not a page. Freya should be able to read
            # a site with a lapsed certificate the same way the user can click through.
            ignore_https_errors=True,
            java_script_enabled=True,
            permissions=[],
        )
        await self.context.add_init_script(_STEALTH_JS)
        try:
            await self.context.add_cookies(search_cookies(self.config))
        except Exception:
            pass

        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
        self.page.set_default_timeout(int(self._bcfg.get("action_timeout_ms", 15000)))
        self.cursor = human.Cursor(self.page.mouse, (width, height))
        print("  [browser] Chromium ready.")

    async def close(self):
        try:
            if self.context:
                await self.context.close()
        except Exception:
            pass
        try:
            if self._pw:
                await self._pw.stop()
        except Exception:
            pass
        self.context = self.page = self._pw = self.cursor = None

    # ── perception ─────────────────────────────────────────────────────────
    async def look(self) -> PageView:
        """Re-read the page. Called after every action — the DOM moves under you."""
        await self.start()
        self.view = await perceive(self.page)
        return self.view

    async def screenshot(self, max_width: int = 1100, quality: int = 68) -> str | None:
        """Base64 JPEG of the viewport, for the agent's vision input."""
        try:
            raw = await self.page.screenshot(type="jpeg", quality=quality, full_page=False)
        except Exception:
            return None
        try:
            from io import BytesIO
            from PIL import Image
            img = Image.open(BytesIO(raw))
            if img.width > max_width:
                img = img.convert("RGB").resize(
                    (max_width, int(img.height * max_width / img.width)), Image.LANCZOS)
                buf = BytesIO()
                img.save(buf, format="JPEG", quality=quality)
                raw = buf.getvalue()
        except Exception:
            pass
        return base64.b64encode(raw).decode()

    # ── navigation ─────────────────────────────────────────────────────────
    async def goto(self, url: str) -> str:
        async with self._lock:
            await self.start()
            if not url.startswith(("http://", "https://", "about:", "file://")):
                url = "https://" + url
            try:
                await self.page.goto(url, wait_until="domcontentloaded",
                                     timeout=int(self._bcfg.get("nav_timeout_ms", 30000)))
            except Exception as e:
                return f"Couldn't open {url}: {str(e)[:200]}"
            await self._after_load()
            return f"Opened {self.page.url}"

    async def search(self, query: str) -> str:
        """Search DuckDuckGo in the real browser, so results can be clicked.

        DDG sometimes answers its JS front-end with an anomaly page (the
        `static-pages/418` block) — reliably so under headless, occasionally on
        a cold profile otherwise. When that happens we fall back to the no-JS
        HTML endpoint, which serves the same results as plain links the agent
        can still click through. Verified: without this, headless browsing
        returns a page with four elements and no results at all.
        """
        result = await self.goto(ddg_search_url(query, self.config))
        await self.look()
        if _looks_blocked(self.view):
            print("  [browser] DDG served its anomaly page — using the no-JS endpoint.")
            result = await self.goto(ddg_html_url(query, self.config))
            await self.look()
        if _looks_blocked(self.view):
            result = await self._offline_results(query)
        return f"Searched DuckDuckGo for '{query}'. {result}"

    async def _offline_results(self, query: str) -> str:
        """Last-resort results page, rendered from the plain-HTTP search.

        Measured behaviour: headless Chromium gets blocked by DDG on both the
        main site and the HTML endpoint, while the same query over plain urllib
        succeeds — the block is on the browser fingerprint, not the query. So we
        fetch the results ourselves and render them into the window as real
        anchors. The agent then clicks through to the destination sites exactly
        as it would on the live results page; only the index page is local.
        """
        from core.browser.search import ddg_search
        loop = asyncio.get_running_loop()
        try:
            results = await loop.run_in_executor(None, ddg_search, query, 8, self.config)
        except Exception as e:
            return f"The search was blocked and the fallback failed: {str(e)[:120]}"
        if not results:
            return f"No results came back for '{query}'."

        rows = "".join(
            f'<li><a href="{r["url"]}">{_esc(r["title"])}</a>'
            f'<p>{_esc(r["snippet"])}</p><cite>{_esc(r["url"])}</cite></li>'
            for r in results
        )
        html = (f'<html><head><title>{_esc(query)} at DuckDuckGo</title></head>'
                f'<body style="font:16px system-ui;max-width:760px;margin:24px auto">'
                f'<h1>Results for "{_esc(query)}"</h1><ol>{rows}</ol></body></html>')
        try:
            await self.page.set_content(html, wait_until="domcontentloaded")
        except Exception as e:
            return f"Couldn't render the fallback results: {str(e)[:120]}"
        await human.think()
        await self.look()
        return f"Got {len(results)} results (via the direct search path)."

    async def go_back(self) -> str:
        async with self._lock:
            try:
                await self.page.go_back(wait_until="domcontentloaded")
            except Exception as e:
                return f"Couldn't go back: {str(e)[:120]}"
            await self._after_load()
            return f"Went back to {self.page.url}"

    async def _after_load(self):
        """Settle: let late scripts run, glance at the page, deal with banners."""
        try:
            await self.page.wait_for_load_state("networkidle", timeout=4000)
        except Exception:
            pass                      # a page that never idles is normal
        await human.think()
        await self._dismiss_consent()
        # People look at the top of a page before doing anything with it.
        if random.random() < 0.6 and self.cursor:
            await self.cursor.drift()

    async def _dismiss_consent(self):
        """Click a reject-cookies button if one is clearly on offer."""
        try:
            view = await perceive(self.page, max_elements=80)
        except Exception:
            return
        for el in view.elements:
            label = el.text.strip().lower()
            if not label or len(label) > 45:
                continue
            if any(phrase in label for phrase in _CONSENT_REJECT):
                await human.think(0.6)
                await self.cursor.click_at(el.x, el.y)
                await human.pause(0.7, 0.3)
                print(f"  [browser] dismissed a consent banner ('{el.text[:30]}')")
                return

    # ── actions ────────────────────────────────────────────────────────────
    async def click(self, index: int) -> str:
        async with self._lock:
            el = self.view.get(index)
            if el is None:
                return f"There's no element [{index}] on this page. Look again."
            await self._bring_into_view(el)
            await human.think()
            before = self.page.url
            try:
                await self.cursor.click_at(el.x, el.y)
            except Exception as e:
                return f"The click on [{index}] failed: {str(e)[:120]}"
            await human.pause(0.55, 0.4)
            await self._settle_after_click(before)
            what = el.text[:60] or f"<{el.tag}>"
            return (f"Clicked [{index}] '{what}'." +
                    (f" It navigated to {self.page.url}" if self.page.url != before else ""))

    async def type_text(self, index: int, text: str, submit: bool = True) -> str:
        async with self._lock:
            el = self.view.get(index)
            if el is None:
                return f"There's no element [{index}] on this page. Look again."
            await self._bring_into_view(el)
            await human.think()
            try:
                await self.cursor.click_at(el.x, el.y)
                await human.pause(0.2, 0.4)
                # Clear whatever is there the way a person does — select all,
                # then overwrite. `fill('')` would skip the keystrokes that
                # search boxes listen for.
                await self.page.keyboard.press("Control+A")
                await human.pause(0.1, 0.4)
                await self.page.keyboard.press("Delete")
                await human.pause(0.15, 0.4)
                await human.type_like_human(
                    self.page.keyboard, text,
                    typo_rate=float(self._bcfg.get("typo_rate", 0.0)),
                )
            except Exception as e:
                return f"Typing into [{index}] failed: {str(e)[:120]}"

            if submit:
                await human.pause(0.35, 0.4)   # the pause before hitting enter
                before = self.page.url
                await self.page.keyboard.press("Enter")
                await human.pause(0.9, 0.3)
                await self._settle_after_click(before)
                return f"Typed '{text[:60]}' into [{index}] and pressed Enter. Now on {self.page.url}"
            return f"Typed '{text[:60]}' into [{index}]."

    async def scroll(self, direction: str = "down", amount: str = "page") -> str:
        async with self._lock:
            height = self.view.viewport_height or 800
            pixels = {"page": int(height * 0.85), "half": int(height * 0.45),
                      "little": 240, "bottom": height * 6}.get(amount, int(height * 0.85))
            if direction == "up":
                pixels = -pixels
            await human.scroll_like_human(self.page.mouse, pixels)
            await human.pause(0.4, 0.4)
            await self.look()
            return f"Scrolled {direction}. Now {self.view.scroll_position}."

    async def press(self, key: str) -> str:
        async with self._lock:
            try:
                await human.think(0.5)
                await self.page.keyboard.press(key)
                await human.pause(0.5, 0.4)
            except Exception as e:
                return f"Couldn't press {key}: {str(e)[:120]}"
            await self.look()
            return f"Pressed {key}."

    async def select_option(self, index: int, value: str) -> str:
        async with self._lock:
            el = self.view.get(index)
            if el is None:
                return f"There's no element [{index}] on this page."
            try:
                handle = await self.page.evaluate_handle(
                    "([x, y]) => document.elementFromPoint(x, y)", [el.x, el.y])
                await handle.as_element().select_option(label=value)
            except Exception:
                try:
                    await handle.as_element().select_option(value=value)
                except Exception as e:
                    return f"Couldn't choose '{value}' in [{index}]: {str(e)[:120]}"
            await human.pause(0.4, 0.3)
            return f"Chose '{value}' in [{index}]."

    async def read_page(self, max_chars: int = 9000) -> str:
        """Full readable text — for when the agent wants to actually study a page."""
        async with self._lock:
            await self.look()
            await human.read(len(self.view.text))
            text = self.view.text[:max_chars]
            more = "" if len(self.view.text) <= max_chars else \
                   f"\n[...{len(self.view.text) - max_chars} more characters]"
            return f"{self.view.title}\n{self.page.url}\n\n{text}{more}"

    # ── internals ──────────────────────────────────────────────────────────
    async def _bring_into_view(self, el) -> None:
        """Scroll an off-screen target into the viewport, then refresh its
        coordinates — everything below it moved when the page scrolled."""
        if el.in_viewport:
            return
        try:
            await human.scroll_like_human(self.page.mouse, int(el.y - self.view.viewport_height * 0.4))
            await human.pause(0.35, 0.4)
            fresh = await self.look()
            match = fresh.get(el.index)
            if match:
                el.x, el.y, el.in_viewport = match.x, match.y, match.in_viewport
        except Exception:
            pass

    async def _settle_after_click(self, previous_url: str):
        """Wait out whatever the click started, then re-perceive.

        The obvious version — `wait_for_load_state()` straight after the click —
        is a race: the old document is still loaded, so it returns instantly and
        we perceive the page we just left. Observed directly in testing (a click
        that had navigated to the article still reported the results URL). So
        first give the navigation a moment to actually begin, the way a person
        waits a beat to see whether anything happened.
        """
        for _ in range(6):
            if self.page.url != previous_url:
                break
            await asyncio.sleep(0.25)

        try:
            await self.page.wait_for_load_state("domcontentloaded", timeout=8000)
        except Exception:
            pass
        if self.page.url != previous_url:
            await self._after_load()
        else:
            try:
                await self.page.wait_for_load_state("networkidle", timeout=2500)
            except Exception:
                pass
        await self.look()


# ══════════════════════════════════════════════════════════════════════════
#  The dedicated browser thread
# ══════════════════════════════════════════════════════════════════════════
class BrowserLoop:
    """Owns the one event loop every browser action runs on.

    Callers on other threads (the voice session, a sub-agent) submit coroutines
    here and get a concurrent Future back. Nothing browser-shaped ever touches
    the audio loop.
    """

    _instance: "BrowserLoop | None" = None
    _guard = threading.Lock()

    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run, daemon=True, name="freya-browser")
        self.thread.start()
        self._browser: HumanBrowser | None = None

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    @classmethod
    def get(cls) -> "BrowserLoop":
        with cls._guard:
            if cls._instance is None:
                cls._instance = BrowserLoop()
            return cls._instance

    def submit(self, coro):
        """Run `coro` on the browser loop. Returns a concurrent.futures.Future."""
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    async def browser(self, config: dict | None = None) -> HumanBrowser:
        """The shared HumanBrowser. Must be awaited from inside the browser loop."""
        if self._browser is None:
            self._browser = HumanBrowser(config)
            await self._browser.start()
        return self._browser


async def get_browser(config: dict | None = None) -> HumanBrowser:
    return await BrowserLoop.get().browser(config)


def shutdown_browser():
    """Close Chromium at app exit. Safe to call from any thread."""
    inst = BrowserLoop._instance
    if inst is None or inst._browser is None:
        return
    try:
        fut = inst.submit(inst._browser.close())
        fut.result(timeout=10)
    except Exception:
        pass
