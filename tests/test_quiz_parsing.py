"""Tests for parse_quiz_response and validate_quiz_questions."""
import json
import pytest

import app


def _q(q="Q1", answer="A", n_opts=4):
    return {
        "q": q,
        "options": [f"opt{i}" for i in range(n_opts)],
        "answer": answer,
        "explain": "explanation",
        "page": 1,
        "topic": "test-topic",
    }


def test_parse_bare_json_object():
    reply = json.dumps({"questions": [_q()]})
    result = app.parse_quiz_response(reply)
    assert len(result) == 1
    assert result[0]["q"] == "Q1"


def test_parse_json_code_fence():
    reply = "```json\n" + json.dumps({"questions": [_q("Q2", "B")]}) + "\n```"
    result = app.parse_quiz_response(reply)
    assert len(result) == 1
    assert result[0]["answer"] == "B"


def test_parse_plain_code_fence():
    reply = "```\n" + json.dumps({"questions": [_q()]}) + "\n```"
    result = app.parse_quiz_response(reply)
    assert len(result) == 1


def test_parse_bare_array_legacy_fallback():
    """If the model returns a bare array instead of {questions: [...]}, still parse it."""
    reply = json.dumps([_q()])
    result = app.parse_quiz_response(reply)
    assert len(result) == 1


def test_parse_invalid_json_raises_json_error():
    with pytest.raises(json.JSONDecodeError):
        app.parse_quiz_response("not json at all")


def test_validate_keeps_well_formed():
    valid = app.validate_quiz_questions([_q()])
    assert len(valid) == 1


def test_validate_drops_missing_required_fields():
    items = [
        {"q": "no opts", "answer": "A", "explain": "e"},
        {"options": ["a", "b", "c", "d"], "answer": "A", "explain": "e"},  # no q
        _q(),  # ok
    ]
    valid = app.validate_quiz_questions(items)
    assert len(valid) == 1
    assert valid[0]["q"] == "Q1"


def test_validate_drops_wrong_option_count():
    items = [_q(n_opts=3), _q(n_opts=5), _q(n_opts=4)]
    valid = app.validate_quiz_questions(items)
    assert len(valid) == 1


def test_validate_drops_invalid_answer_letter():
    items = [_q(answer="E"), _q(answer="X"), _q(answer="A")]
    valid = app.validate_quiz_questions(items)
    assert len(valid) == 1
    assert valid[0]["answer"] == "A"


def test_validate_normalizes_answer_case_and_whitespace():
    items = [{**_q(), "answer": " b "}]
    valid = app.validate_quiz_questions(items)
    assert valid[0]["answer"] == "B"


def test_validate_rejects_non_list_options():
    items = [{**_q(), "options": "ABCD"}]
    valid = app.validate_quiz_questions(items)
    assert valid == []
