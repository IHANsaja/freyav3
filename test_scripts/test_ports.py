"""Freya's ports follow what start-freya picked, with 8000/3000 as defaults."""

import importlib

import pytest

from config import ports


def test_defaults(monkeypatch):
    monkeypatch.delenv("FREYA_API_PORT", raising=False)
    monkeypatch.delenv("FREYA_UI_PORT", raising=False)
    assert (ports.api_port(), ports.ui_port()) == (8000, 3000)
    assert ports.dashboard_origins() == ["http://localhost:3000", "http://127.0.0.1:3000"]


def test_picked_ports_are_used(monkeypatch):
    monkeypatch.setenv("FREYA_API_PORT", "8001")
    monkeypatch.setenv("FREYA_UI_PORT", "3002")
    assert ports.api_port() == 8001
    assert ports.ui_url("/trading") == "http://localhost:3002/trading"
    assert ports.dashboard_origins() == ["http://localhost:3002", "http://127.0.0.1:3002"]


@pytest.mark.parametrize("bad", ["", "abc", "0", "70000", "-5"])
def test_bad_values_fall_back(monkeypatch, bad):
    monkeypatch.setenv("FREYA_API_PORT", bad)
    assert ports.api_port() == 8000


def test_server_and_trading_follow_the_dashboard_port(monkeypatch):
    monkeypatch.setenv("FREYA_UI_PORT", "3007")
    import core.trading.tools as tools
    tools = importlib.reload(tools)
    assert tools.LAB_URL == "http://localhost:3007/trading"
