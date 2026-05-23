"""Tests for the small Discord/OpenAI helpers."""
from datetime import datetime, timedelta, timezone

import app


# --- format_time_remaining ---

def test_format_time_remaining_positive():
    end = datetime.now(timezone.utc) + timedelta(minutes=5, seconds=30)
    minutes, seconds = app.format_time_remaining(end)
    assert minutes == 5
    # Allow small clock-jitter between the two datetime.now() calls
    assert 28 <= seconds <= 30


def test_format_time_remaining_already_past_is_zero():
    end = datetime.now(timezone.utc) - timedelta(minutes=5)
    minutes, seconds = app.format_time_remaining(end)
    assert minutes == 0
    assert seconds == 0


def test_format_time_remaining_exactly_now_is_zero():
    end = datetime.now(timezone.utc)
    minutes, seconds = app.format_time_remaining(end)
    assert minutes == 0
    assert seconds == 0


# --- truncate_for_discord ---

def test_truncate_noop_under_limit():
    short = "hello world"
    assert app.truncate_for_discord(short) == short


def test_truncate_basic_long_text():
    long_text = "x" * 3000
    result = app.truncate_for_discord(long_text)
    assert len(result) <= 2000
    assert result.endswith("...")


def test_truncate_closes_open_triple_backtick_fence():
    text = "before\n```python\n" + ("payload\n" * 500)
    result = app.truncate_for_discord(text)
    assert len(result) <= 2000
    # An odd number of triple-backtick fences would break Discord rendering.
    assert result.count("```") % 2 == 0


def test_truncate_leaves_balanced_fences_alone():
    text = "before\n```python\ncode\n```\n" + "x" * 3000
    result = app.truncate_for_discord(text)
    assert len(result) <= 2000
    assert result.count("```") % 2 == 0


# --- chunk_mentions ---

def test_chunk_mentions_empty():
    assert app.chunk_mentions([], "Players") == []


def test_chunk_mentions_single_page_uses_base_name():
    result = app.chunk_mentions(["123", "456"], "Players")
    assert result == [("Players", "<@123>, <@456>")]


def test_chunk_mentions_multi_page_paginates_name():
    # Snowflake IDs are 17-19 digits; <@id> is ~21 chars + ", "
    user_ids = [str(10**17 + i) for i in range(50)]
    result = app.chunk_mentions(user_ids, "Players", max_chars=200)
    assert len(result) > 1
    assert result[0][0] == f"Players (1/{len(result)})"
    for name, value in result:
        assert len(value) <= 200
    # Round-trip: concatenating all values should recover all mentions
    all_mentions = ", ".join(value for _, value in result)
    for uid in user_ids:
        assert f"<@{uid}>" in all_mentions


def test_chunk_mentions_respects_max_chars():
    # 30 IDs of length ~20 chars each, force tiny chunks
    user_ids = [str(10**17 + i) for i in range(30)]
    result = app.chunk_mentions(user_ids, "Players", max_chars=100)
    for _, value in result:
        assert len(value) <= 100


# --- model_supports_temperature ---

def test_temperature_supported_for_haiku_and_sonnet():
    assert app.model_supports_temperature("claude-haiku-4-5")
    assert app.model_supports_temperature("claude-sonnet-4-6")


def test_temperature_supported_for_opus_4_6():
    # Opus 4.6 and earlier accept temperature; only Opus 4.7+ rejects it.
    assert app.model_supports_temperature("claude-opus-4-6")
    assert app.model_supports_temperature("claude-opus-4-5")


def test_temperature_rejected_for_opus_4_7():
    assert not app.model_supports_temperature("claude-opus-4-7")


def test_temperature_default_true_for_unknown_or_none():
    assert app.model_supports_temperature(None)
    assert app.model_supports_temperature("")
    assert app.model_supports_temperature("some-future-model")
