"""open_trading_lab: follow the page's session, open the browser only when needed,
and never report 'opened' without the page confirming it."""

import asyncio
import json

import pytest

from core.trading import tools as t
from core.trading import guide


class Ctx:
    def __init__(self, source="live"):
        self.source = source
        self.config = {}


@pytest.fixture
def opened(monkeypatch):
    calls = []
    monkeypatch.setattr(t.webbrowser, "open", lambda url: calls.append(url))
    real_sleep = asyncio.sleep
    monkeypatch.setattr(t.asyncio, "sleep", lambda s: real_sleep(0))
    return calls


def run(args, ctx=None):
    return json.loads(asyncio.run(t.open_trading_lab(args, ctx or Ctx())))


def test_already_open_reuses_page_session_without_new_tab(monkeypatch, opened):
    monkeypatch.setattr(guide, "_current_view", lambda: {"session_id": "abc", "candle_id": None})
    out = run({})
    assert out == {"status": "already_open", "session_id": "abc",
                   "note": "The Trading Lab is already open in his browser on this session."}
    assert opened == []


def test_opens_browser_and_waits_for_page(monkeypatch, opened):
    views = iter([None, None, {"session_id": "live1", "candle_id": None}])
    monkeypatch.setattr(guide, "_current_view", lambda: next(views, {"session_id": "live1"}))
    out = run({})
    assert out["status"] == "opened" and out["session_id"] == "live1"
    assert opened == [t.LAB_URL]


def test_never_claims_open_without_confirmation(monkeypatch, opened):
    monkeypatch.setattr(guide, "_current_view", lambda: None)
    out = run({})
    assert out["status"] == "not_confirmed"
    assert "Do not say it is open" in out["note"]
