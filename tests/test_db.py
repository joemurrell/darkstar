"""Tests for the QuizStore persistence layer, run against an in-memory DB."""
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

import db


def _questions(n=3):
    return [
        {
            "q": f"Question {i}?",
            "options": ["a", "b", "c", "d"],
            "answer": "A",
            "explain": f"explanation {i}",
            "topic": f"topic-{i}",
            "page": i + 1,
        }
        for i in range(n)
    ]


def _quiz_kwargs(channel_id=100, **overrides):
    now = datetime.now(timezone.utc)
    base = {
        "channel_id": channel_id,
        "guild_id": 200,
        "initiator_id": 300,
        "topic": "radio-procedures",
        "started_at": now,
        "end_time": now + timedelta(minutes=15),
        "duration_minutes": 15,
        "questions": _questions(),
    }
    base.update(overrides)
    return base


@pytest_asyncio.fixture
async def store():
    s = await db.QuizStore.connect(":memory:")
    yield s
    await s.close()


async def test_create_quiz_returns_id_and_loads_active(store):
    quiz_id = await store.create_quiz(**_quiz_kwargs())
    assert isinstance(quiz_id, int)

    active = await store.load_active_quizzes()
    assert len(active) == 1
    q = active[0]
    assert q["quiz_id"] == quiz_id
    assert q["channel_id"] == 100
    assert q["guild_id"] == 200
    assert q["initiator_id"] == 300
    assert q["topic"] == "radio-procedures"
    assert q["duration_minutes"] == 15
    assert len(q["questions"]) == 3
    assert q["answers"] == {}


async def test_questions_roundtrip_in_order_with_options(store):
    await store.create_quiz(**_quiz_kwargs())
    q = (await store.load_active_quizzes())[0]
    # Order preserved by position
    assert [item["q"] for item in q["questions"]] == ["Question 0?", "Question 1?", "Question 2?"]
    # Options deserialized back to a list
    assert q["questions"][0]["options"] == ["a", "b", "c", "d"]
    assert q["questions"][2]["page"] == 3


async def test_datetimes_roundtrip_as_aware(store):
    kwargs = _quiz_kwargs()
    await store.create_quiz(**kwargs)
    q = (await store.load_active_quizzes())[0]
    assert q["end_time"] == kwargs["end_time"]
    assert q["end_time"].tzinfo is not None


async def test_record_answer_and_load(store):
    quiz_id = await store.create_quiz(**_quiz_kwargs())
    now = datetime.now(timezone.utc)
    await store.record_answer(quiz_id=quiz_id, position=0, user_id=42, choice="B", answered_at=now)
    await store.record_answer(quiz_id=quiz_id, position=1, user_id=42, choice="C", answered_at=now)
    await store.record_answer(quiz_id=quiz_id, position=0, user_id=99, choice="A", answered_at=now)

    answers = (await store.load_active_quizzes())[0]["answers"]
    assert answers == {42: {0: "B", 1: "C"}, 99: {0: "A"}}


async def test_record_answer_overwrites(store):
    quiz_id = await store.create_quiz(**_quiz_kwargs())
    now = datetime.now(timezone.utc)
    await store.record_answer(quiz_id=quiz_id, position=0, user_id=42, choice="A", answered_at=now)
    await store.record_answer(quiz_id=quiz_id, position=0, user_id=42, choice="D", answered_at=now)

    answers = (await store.load_active_quizzes())[0]["answers"]
    assert answers == {42: {0: "D"}}


async def test_complete_quiz_excluded_from_active(store):
    quiz_id = await store.create_quiz(**_quiz_kwargs())
    await store.complete_quiz(quiz_id)
    assert await store.load_active_quizzes() == []


async def test_one_active_quiz_per_channel_enforced(store):
    await store.create_quiz(**_quiz_kwargs(channel_id=100))
    with pytest.raises(Exception):
        await store.create_quiz(**_quiz_kwargs(channel_id=100))


async def test_channel_can_start_new_quiz_after_completion(store):
    first = await store.create_quiz(**_quiz_kwargs(channel_id=100))
    await store.complete_quiz(first)
    # Same channel, new quiz — should succeed now that the first is completed.
    second = await store.create_quiz(**_quiz_kwargs(channel_id=100))
    assert second != first
    active = await store.load_active_quizzes()
    assert len(active) == 1
    assert active[0]["quiz_id"] == second


async def test_multiple_channels_independent(store):
    await store.create_quiz(**_quiz_kwargs(channel_id=1))
    await store.create_quiz(**_quiz_kwargs(channel_id=2))
    active = await store.load_active_quizzes()
    assert {q["channel_id"] for q in active} == {1, 2}
