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


# --- get_user_stats ---

async def test_get_user_stats_counts_correct_and_accuracy(store):
    now = datetime.now(timezone.utc)
    # _questions() all have answer "A". Quiz 1: user 42 gets q0 right, q1 wrong.
    q1 = await store.create_quiz(**_quiz_kwargs(channel_id=1))
    await store.record_answer(quiz_id=q1, position=0, user_id=42, choice="A", answered_at=now)
    await store.record_answer(quiz_id=q1, position=1, user_id=42, choice="B", answered_at=now)
    await store.complete_quiz(q1)
    # Quiz 2: user 42 gets q0 right.
    q2 = await store.create_quiz(**_quiz_kwargs(channel_id=2))
    await store.record_answer(quiz_id=q2, position=0, user_id=42, choice="A", answered_at=now)
    await store.complete_quiz(q2)

    stats = await store.get_user_stats(42)
    assert stats["quizzes"] == 2
    assert stats["answered"] == 3
    assert stats["correct"] == 2
    assert stats["accuracy"] == 2 / 3


async def test_get_user_stats_excludes_active_quizzes(store):
    # Answers in an active (not completed) quiz must not count.
    qid = await store.create_quiz(**_quiz_kwargs(channel_id=1))
    await store.record_answer(quiz_id=qid, position=0, user_id=42, choice="A", answered_at=datetime.now(timezone.utc))
    assert await store.get_user_stats(42) == {"quizzes": 0, "answered": 0, "correct": 0, "accuracy": 0.0}


async def test_get_user_stats_unknown_user_is_zero(store):
    qid = await store.create_quiz(**_quiz_kwargs())
    await store.complete_quiz(qid)
    stats = await store.get_user_stats(999)
    assert stats["answered"] == 0
    assert stats["correct"] == 0
    assert stats["accuracy"] == 0.0


async def test_get_user_stats_is_per_user(store):
    now = datetime.now(timezone.utc)
    qid = await store.create_quiz(**_quiz_kwargs())
    await store.record_answer(quiz_id=qid, position=0, user_id=1, choice="A", answered_at=now)  # correct
    await store.record_answer(quiz_id=qid, position=0, user_id=2, choice="D", answered_at=now)  # wrong
    await store.complete_quiz(qid)

    assert (await store.get_user_stats(1))["correct"] == 1
    assert (await store.get_user_stats(2))["correct"] == 0


# --- get_leaderboard ---

async def _answer_all(store, quiz_id, user_id, choices, now=None):
    """Record `choices` (by position) for a user, then nothing else."""
    now = now or datetime.now(timezone.utc)
    for pos, choice in enumerate(choices):
        await store.record_answer(quiz_id=quiz_id, position=pos, user_id=user_id, choice=choice, answered_at=now)


async def test_get_leaderboard_ranks_by_correct_desc(store):
    # _questions() all answer "A". user 1 gets 3/3, user 2 gets 1/3, user 3 gets 2/3.
    qid = await store.create_quiz(**_quiz_kwargs(guild_id=200))
    await _answer_all(store, qid, 1, ["A", "A", "A"])
    await _answer_all(store, qid, 2, ["A", "B", "C"])
    await _answer_all(store, qid, 3, ["A", "A", "D"])
    await store.complete_quiz(qid)

    board = await store.get_leaderboard(200)
    assert [r["user_id"] for r in board] == [1, 3, 2]
    assert [r["correct"] for r in board] == [3, 2, 1]
    assert board[0]["accuracy"] == 1.0


async def test_get_leaderboard_tiebreak_by_accuracy(store):
    # Both users get 2 correct, but user 5 answered only 2 (100%) vs user 4's 3 (67%).
    qid = await store.create_quiz(**_quiz_kwargs(guild_id=200))
    await _answer_all(store, qid, 4, ["A", "A", "D"])  # 2/3
    await _answer_all(store, qid, 5, ["A", "A"])       # 2/2
    await store.complete_quiz(qid)

    board = await store.get_leaderboard(200)
    assert [r["user_id"] for r in board] == [5, 4]


async def test_get_leaderboard_is_guild_scoped(store):
    q_a = await store.create_quiz(**_quiz_kwargs(channel_id=1, guild_id=200))
    await _answer_all(store, q_a, 1, ["A", "A", "A"])
    await store.complete_quiz(q_a)
    q_b = await store.create_quiz(**_quiz_kwargs(channel_id=2, guild_id=999))
    await _answer_all(store, q_b, 2, ["A", "A", "A"])
    await store.complete_quiz(q_b)

    board = await store.get_leaderboard(200)
    assert [r["user_id"] for r in board] == [1]


async def test_get_leaderboard_excludes_active_quizzes(store):
    qid = await store.create_quiz(**_quiz_kwargs(guild_id=200))
    await _answer_all(store, qid, 1, ["A", "A", "A"])
    # Not completed -> not counted.
    assert await store.get_leaderboard(200) == []


async def test_get_leaderboard_respects_limit(store):
    qid = await store.create_quiz(**_quiz_kwargs(guild_id=200))
    for uid in range(1, 6):
        await _answer_all(store, qid, uid, ["A"])
    await store.complete_quiz(qid)

    board = await store.get_leaderboard(200, limit=3)
    assert len(board) == 3


async def test_get_leaderboard_empty_when_no_history(store):
    assert await store.get_leaderboard(200) == []


# --- guild_id=None edge cases ---

async def test_load_active_quizzes_with_null_guild_id(store):
    quiz_id = await store.create_quiz(**_quiz_kwargs(guild_id=None))
    active = await store.load_active_quizzes()
    assert len(active) == 1
    assert active[0]["quiz_id"] == quiz_id
    assert active[0]["guild_id"] is None


async def test_leaderboard_excludes_null_guild_quizzes_from_other_guild(store):
    # A quiz with guild_id=None should not appear on guild 200's leaderboard.
    qid = await store.create_quiz(**_quiz_kwargs(guild_id=None))
    await _answer_all(store, qid, 1, ["A", "A", "A"])
    await store.complete_quiz(qid)

    board = await store.get_leaderboard(200)
    assert board == []


# --- get_leaderboard tiebreak: fewer answered wins ---

async def test_get_leaderboard_tiebreak_by_fewer_answered(store):
    # User 7 gets 1 correct at 100% accuracy; user 6 gets 1 correct at 50%.
    # Tiebreak by accuracy → user 7 ranked above user 6.
    qid = await store.create_quiz(**_quiz_kwargs(guild_id=200))
    now = datetime.now(timezone.utc)
    await store.record_answer(quiz_id=qid, position=0, user_id=6, choice="A", answered_at=now)
    await store.record_answer(quiz_id=qid, position=1, user_id=6, choice="D", answered_at=now)
    await store.record_answer(quiz_id=qid, position=0, user_id=7, choice="A", answered_at=now)
    await store.complete_quiz(qid)

    board = await store.get_leaderboard(200)
    user_ids = [r["user_id"] for r in board]
    assert user_ids.index(7) < user_ids.index(6)


# --- get_user_stats: no activity at all ---

async def test_get_user_stats_no_quizzes_ever(store):
    stats = await store.get_user_stats(42)
    assert stats == {"quizzes": 0, "answered": 0, "correct": 0, "accuracy": 0.0}
