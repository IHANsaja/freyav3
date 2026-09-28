"""A refused Gemini key stops the session at once; .env values are cleaned up."""

import pytest

import config
from core.live_protocol import LiveRoute, LIVE_MODEL, is_auth_failure
from core.model import is_rotation


class Closed(Exception):
    pass


# Exact close reasons the Live API sends for a bad key (captured 2026-09-28).
AQ_KEY_REJECTED = Closed("1008 None. Request had invalid authentication credentials. "
                         "Expected OAuth 2 access token, login cookie or other valid authentication c")
BAD_KEY = Closed("1007 None. API key not valid. Please pass a valid API key.")
EMPTY_KEY = Closed("1008 (policy violation) Method doesn't allow unregistered callers "
                   "(callers without established identity). Please use API Key or other form of API c")


@pytest.mark.parametrize("exc", [AQ_KEY_REJECTED, BAD_KEY, EMPTY_KEY])
def test_key_rejections_are_auth_failures(exc):
    assert is_auth_failure(exc)
    # ...and never mistaken for a routine rotation or a model fallback.
    assert not is_rotation(exc)
    route = LiveRoute(LIVE_MODEL, {"live": {"fallback_model": "gemini-3.1-flash-live-preview"}})
    assert route.fallback(exc, repeated=2) is None


@pytest.mark.parametrize("text", [
    "1011 None. Internal error encountered.",
    "1008 None. failed to close the connection after receiving a GoAway signal",
    "keepalive ping timeout",
])
def test_transient_errors_are_not_auth_failures(text):
    assert not is_auth_failure(Closed(text))


@pytest.mark.parametrize("raw, expected", [
    ("AIzaKey", "AIzaKey"),
    ("  AIzaKey  ", "AIzaKey"),
    ('"AIzaKey"', "AIzaKey"),
    ("'AIzaKey'", "AIzaKey"),
    ("﻿AIzaKey", "AIzaKey"),
])
def test_get_api_key_cleans_pasted_values(monkeypatch, raw, expected):
    monkeypatch.setenv("GEMINI_API_KEY", raw)
    assert config.get_api_key() == expected


@pytest.mark.parametrize("raw", ["", "   ", "PASTE_YOUR_GEMINI_API_KEY_HERE", '""'])
def test_get_api_key_rejects_placeholder_and_blank(monkeypatch, raw):
    monkeypatch.setenv("GEMINI_API_KEY", raw)
    with pytest.raises(ValueError, match="aistudio.google.com"):
        config.get_api_key()


def test_agent_key_skips_placeholder_secondary(monkeypatch):
    monkeypatch.setenv("GEMINI_AGENT_API_KEY", "PASTE_YOUR_GEMINI_API_KEY_HERE")
    monkeypatch.delenv("GEMINI_MEMORY_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaMain")
    assert config.get_agent_api_key() == "AIzaMain"
