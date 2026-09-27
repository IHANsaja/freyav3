"""Live-model fallback on repeated 1011s, and spoken key names for press_key."""

from core.live_protocol import LiveRoute, LIVE_MODEL


class Closed(Exception):
    pass


def route():
    return LiveRoute(LIVE_MODEL, {"live": {"fallback_model": "gemini-3.1-flash-live-preview"}})


def test_first_1011_retries_same_model():
    r = route()
    assert r.fallback(Closed("1011 None. Internal error encountered."), repeated=1) is None
    assert r.model == LIVE_MODEL


def test_second_1011_falls_back():
    r = route()
    assert r.fallback(Closed("1011 None. Internal error encountered."), repeated=2) \
        == "gemini-3.1-flash-live-preview"


def test_unrelated_error_never_falls_back():
    r = route()
    assert r.fallback(Closed("401 API key not valid"), repeated=5) is None


class _ServerError(Exception):
    code = 503


class _FakeModels:
    def __init__(self, down):
        self.down, self.calls = down, []

    async def generate_content(self, **kw):
        self.calls.append(kw["model"])
        if kw["model"] in self.down:
            raise _ServerError("503 UNAVAILABLE: model overloaded")
        return type("R", (), {"text": "ok", "usage_metadata": None})()


def _client(down):
    models = _FakeModels(down)
    return type("C", (), {"aio": type("A", (), {"models": models})()})(), models


_FAST = {"quota": {"default_rpm": 100000, "max_retries": 0, "max_retry_wait_s": 1}}


def test_overloaded_model_falls_back_once():
    import asyncio
    from core.quota import generate
    client, models = _client({"gemini-3.5-flash"})
    result = asyncio.run(generate(client, quota_config=_FAST, model="gemini-3.5-flash", contents="x"))
    assert result.text == "ok"
    assert models.calls == ["gemini-3.5-flash", "gemini-3.5-flash-lite"]


def test_fallback_is_not_retried_in_a_loop():
    import asyncio
    import pytest
    from core.quota import generate, QuotaError
    client, models = _client({"gemini-3.5-flash", "gemini-3.5-flash-lite"})
    with pytest.raises(QuotaError):
        asyncio.run(generate(client, quota_config=_FAST, model="gemini-3.5-flash", contents="x"))
    assert models.calls == ["gemini-3.5-flash", "gemini-3.5-flash-lite"]


def test_key_aliases():
    from core.vision import _key_name
    assert _key_name("left windows") == "winleft"
    assert _key_name("Start") == "win"
    assert _key_name("control") == "ctrl"
    assert _key_name("enter") == "enter"
    assert _key_name("the big red button") is None


def test_unknown_key_reports_failure_without_pressing():
    from core.vision import press_key
    assert press_key("the big red button").startswith("Key press failed")
    assert press_key("ctrl+banana").startswith("Key press failed")
