"""Tests for the question-bank loader and sampler."""
import json

import app


def _q(topic: str, n: int) -> dict:
    """A schema-valid question dict with a distinguishable question text."""
    return {
        "q": f"Question {n} about {topic}?",
        "options": ["alpha", "bravo", "charlie", "delta"],
        "answer": "A",
        "explain": f"See p.{n}.",
        "page": n,
        "topic": topic,
    }


def _bank(topics, per_topic=3):
    bank = []
    n = 0
    for t in topics:
        for _ in range(per_topic):
            n += 1
            bank.append(_q(t, n))
    return bank


# --- load_question_bank ---

def test_load_missing_file_returns_empty(tmp_path):
    assert app.load_question_bank(str(tmp_path / "nope.json")) == []


def test_load_bad_json_returns_empty(tmp_path):
    p = tmp_path / "bank.json"
    p.write_text("{not json", encoding="utf-8")
    assert app.load_question_bank(str(p)) == []


def test_load_non_list_returns_empty(tmp_path):
    p = tmp_path / "bank.json"
    p.write_text(json.dumps({"questions": []}), encoding="utf-8")
    assert app.load_question_bank(str(p)) == []


def test_load_validates_and_drops_malformed(tmp_path):
    good = _q("fuel-system", 1)
    bad = {"q": "missing options", "answer": "A", "explain": "x"}  # no options
    three_options = _q("radio", 2)
    three_options["options"] = ["a", "b", "c"]  # wrong length -> dropped
    p = tmp_path / "bank.json"
    p.write_text(json.dumps([good, bad, three_options]), encoding="utf-8")
    loaded = app.load_question_bank(str(p))
    assert len(loaded) == 1
    assert loaded[0]["topic"] == "fuel-system"


# --- sample_questions ---

def test_sample_empty_bank_returns_empty():
    assert app.sample_questions([], 5) == []


def test_sample_zero_requested_returns_empty():
    assert app.sample_questions(_bank(["a", "b"]), 0) == []


def test_sample_returns_requested_count():
    bank = _bank(["a", "b", "c", "d"], per_topic=3)  # 12 questions
    result = app.sample_questions(bank, 5)
    assert len(result) == 5


def test_sample_no_duplicates_within_quiz():
    bank = _bank(["a", "b", "c", "d"], per_topic=3)
    result = app.sample_questions(bank, 10)
    texts = [q["q"] for q in result]
    assert len(texts) == len(set(texts))


def test_sample_more_than_available_returns_all():
    bank = _bank(["a", "b"], per_topic=2)  # 4 questions
    result = app.sample_questions(bank, 10)
    assert len(result) == 4


def test_sample_spreads_across_topics():
    # 6 topics; asking for 5 (< topic count) should yield 5 distinct topics
    # because round-robin takes one per topic before repeating any.
    bank = _bank(["t0", "t1", "t2", "t3", "t4", "t5"], per_topic=4)
    result = app.sample_questions(bank, 5)
    topics = [q["topic"] for q in result]
    assert len(set(topics)) == 5


def test_sample_topic_filter_matches_tag():
    bank = _bank(["fuel-system", "radio-procedures", "engine-trim"], per_topic=3)
    result = app.sample_questions(bank, 5, topic="radio")
    assert result  # found matches
    assert all("radio" in q["topic"] for q in result)


def test_sample_topic_filter_matches_question_text():
    bank = [_q("misc", 1)]  # text is "Question 1 about misc?"
    result = app.sample_questions(bank, 3, topic="misc")
    assert len(result) == 1


def test_sample_topic_filter_no_match_returns_empty():
    bank = _bank(["fuel-system", "radio-procedures"], per_topic=3)
    assert app.sample_questions(bank, 5, topic="nonexistent-topic") == []
