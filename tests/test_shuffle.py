"""Tests for shuffle_quiz_options."""
import random

import app


def _question(answer_idx=0):
    """A question where the correct option is uniquely identifiable as 'correct'."""
    options = ["wrong0", "wrong1", "wrong2", "wrong3"]
    options[answer_idx] = "correct"
    return {
        "q": "Question text",
        "options": options,
        "answer": chr(ord("A") + answer_idx),
        "explain": "explanation",
        "page": 42,
        "topic": "test-topic",
    }


def test_shuffle_preserves_correct_answer():
    # Try a handful of seeds to make sure the invariant holds across permutations
    for seed in range(20):
        random.seed(seed)
        q = _question(answer_idx=0)
        shuffled = app.shuffle_quiz_options(q)
        answer_idx = ord(shuffled["answer"]) - ord("A")
        assert shuffled["options"][answer_idx] == "correct", (
            f"seed={seed}: answer letter {shuffled['answer']} doesn't point at the correct option"
        )


def test_shuffle_preserves_all_fields():
    q = {
        "q": "Q1",
        "options": ["a", "b", "c", "d"],
        "answer": "A",
        "explain": "e",
        "topic": "t",
        "page": 1,
        "note": "should not be dropped",
        "future_field": [1, 2, 3],
    }
    shuffled = app.shuffle_quiz_options(q)
    assert shuffled["note"] == "should not be dropped"
    assert shuffled["future_field"] == [1, 2, 3]
    assert shuffled["topic"] == "t"
    assert shuffled["page"] == 1
    assert shuffled["q"] == "Q1"
    assert shuffled["explain"] == "e"


def test_shuffle_handles_lowercase_answer():
    q = _question(answer_idx=2)
    q["answer"] = "c"  # lowercase
    shuffled = app.shuffle_quiz_options(q)
    answer_idx = ord(shuffled["answer"]) - ord("A")
    assert shuffled["options"][answer_idx] == "correct"


def test_shuffle_does_not_mutate_original():
    q = _question(answer_idx=1)
    original_options = list(q["options"])
    original_answer = q["answer"]
    app.shuffle_quiz_options(q)
    assert q["options"] == original_options
    assert q["answer"] == original_answer
