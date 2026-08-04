"""
Freya's own browser stack — written from scratch, replacing the browser-use library.

Why it exists
-------------
`browser-use` was a black box: its own LLM loop, its own prompts, its own DOM
serializer, its own opinions about safety and pacing. We could not teach it to
move like a person, could not point it at DuckDuckGo, and could not stop it
refusing pages. It also pinned google-genai<2 for the whole project.

This package is the replacement, in four small pieces:

  human.py       — the motion layer. Bezier mouse paths, per-character typing
                   rhythm, easing scrolls, reading pauses. This is what makes
                   Freya's browsing look human rather than scripted.
  perception.py  — the eyes. Turns a live page into an indexed list of things
                   a person could actually click or type into, plus readable text.
  driver.py      — the hands. A persistent, stealthed Chromium context wired to
                   the two modules above.
  search.py      — DuckDuckGo, with SafeSearch off by default.
  agent.py       — the brain. A Gemini loop that perceives, decides, acts, repeats.

Playwright is kept as the transport (it speaks CDP to Chromium); everything
above the wire protocol is ours.
"""

from core.browser.driver import HumanBrowser, get_browser, shutdown_browser
from core.browser.search import ddg_search, ddg_news, ddg_search_url
from core.browser.agent import BrowserAgent

__all__ = [
    "HumanBrowser", "get_browser", "shutdown_browser",
    "ddg_search", "ddg_news", "ddg_search_url",
    "BrowserAgent",
]
