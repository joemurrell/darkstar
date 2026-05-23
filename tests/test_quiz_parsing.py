"""
Tests for validate_quiz_questions.

`parse_quiz_response` is gone — we now use Claude's forced tool-use, which
returns a parsed dict directly on the tool_use block. validate_quiz_questions
remains as the second line of defense against malformed tool inputs.
"""
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


def test_validate_skips_non_dict_items():
    """
    Defensive: even though Claude's input_schema enforces shape, validate
    still skips ints / strings / Nones rather than raising TypeError on
    `k in item`.
    """
    items = [_q(), 42, "not a dict", None, [1, 2, 3], _q("Q2")]
    valid = app.validate_quiz_questions(items)
    assert len(valid) == 2
    assert valid[0]["q"] == "Q1"
    assert valid[1]["q"] == "Q2"


def test_validate_does_not_mutate_input():
    """Normalizing the answer letter must not modify the caller's dicts."""
    original = {**_q(), "answer": " b "}
    items = [original]
    app.validate_quiz_questions(items)
    assert original["answer"] == " b "


def test_quiz_tool_schema_shape():
    """
    Sanity-check the QUIZ_TOOL spec — Claude rejects schemas that violate
    structured-output constraints (e.g. missing additionalProperties: false).
    """
    schema = app.QUIZ_TOOL["input_schema"]
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    question_schema = schema["properties"]["questions"]["items"]
    assert question_schema["additionalProperties"] is False
    # Topic + page must be required so the dedup logic can't collapse on
    # missing topics — see CLAUDE.md → Deduplication.
    assert set(question_schema["required"]) == {
        "q", "options", "answer", "explain", "page", "topic"
    }
    assert question_schema["properties"]["answer"]["enum"] == ["A", "B", "C", "D"]
