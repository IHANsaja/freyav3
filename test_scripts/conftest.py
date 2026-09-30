"""Shared pytest setup for test_scripts."""

import pytest


@pytest.fixture(autouse=True)
def _isolated_quota_state(tmp_path, monkeypatch):
    """Keep tests off the real daily request counts in memory/quota_state.json.

    core/quota.py persists today's per-model request counts so the free-tier
    daily limit is tracked across restarts; a test run must not add fake
    requests to them, or mark a real model as used up for the day.
    """
    from core import quota
    quota.reset()
    monkeypatch.setattr(quota, "_STATE_PATH", str(tmp_path / "quota_state.json"))
    yield
    quota.reset()
