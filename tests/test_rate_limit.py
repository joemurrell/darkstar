"""Tests for the per-user /ask rate limiter (rate_limit_ask)."""
from datetime import datetime, timedelta, timezone

import pytest

import app


@pytest.fixture(autouse=True)
def fresh_history(monkeypatch):
    """Each test gets an empty history and a known limit/window."""
    monkeypatch.setattr(app, "ASK_HISTORY", {})
    monkeypatch.setattr(app, "ASK_RATE_LIMIT", 3)
    monkeypatch.setattr(app, "ASK_RATE_WINDOW_SECONDS", 3600)


def test_allows_up_to_the_limit():
    assert app.rate_limit_ask(1) is None
    assert app.rate_limit_ask(1) is None
    assert app.rate_limit_ask(1) is None


def test_blocks_over_the_limit_and_returns_seconds():
    for _ in range(3):
        assert app.rate_limit_ask(1) is None
    retry = app.rate_limit_ask(1)
    assert isinstance(retry, int)
    assert 0 < retry <= 3600


def test_limit_is_per_user():
    for _ in range(3):
        app.rate_limit_ask(1)
    assert app.rate_limit_ask(1) is not None  # user 1 blocked
    assert app.rate_limit_ask(2) is None      # user 2 unaffected


def test_window_expiry_frees_a_slot():
    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    for i in range(3):
        assert app.rate_limit_ask(1, now=base + timedelta(seconds=i)) is None
    # Still inside the window -> blocked
    assert app.rate_limit_ask(1, now=base + timedelta(minutes=30)) is not None
    # Past the window relative to the first three -> allowed again
    assert app.rate_limit_ask(1, now=base + timedelta(hours=1, seconds=1)) is None


def test_disabled_when_limit_zero(monkeypatch):
    monkeypatch.setattr(app, "ASK_RATE_LIMIT", 0)
    for _ in range(100):
        assert app.rate_limit_ask(1) is None
