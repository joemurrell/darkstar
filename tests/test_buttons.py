"""Tests for the persistent quiz answer buttons (custom_id encoding + view)."""
import re

import app


def test_custom_id_format():
    assert app.quiz_button_custom_id(12345, 0, "A") == "quiz:12345:0:A"


def test_custom_id_matches_template_and_captures():
    cid = app.quiz_button_custom_id(987654321, 4, "C")
    m = re.fullmatch(app.QUIZ_BUTTON_TEMPLATE, cid)
    assert m is not None
    assert m.group("channel") == "987654321"
    assert m.group("q") == "4"
    assert m.group("choice") == "C"


def test_custom_id_is_channel_scoped():
    # Same question/choice in different channels must produce distinct ids so
    # concurrent quizzes don't collide when handlers are registered globally.
    a = app.quiz_button_custom_id(111, 0, "A")
    b = app.quiz_button_custom_id(222, 0, "A")
    assert a != b


def test_template_rejects_bad_choice():
    # Only A-D are valid answer letters; anything else must not match.
    assert re.fullmatch(app.QUIZ_BUTTON_TEMPLATE, "quiz:1:0:E") is None
    assert re.fullmatch(app.QUIZ_BUTTON_TEMPLATE, "quiz:1:0:") is None


def test_build_question_view_one_button_per_option():
    view = app.build_question_view(555, 2, ["w", "x", "y", "z"])
    assert len(view.children) == 4
    assert view.timeout is None
    cids = [child.custom_id for child in view.children]
    assert cids == ["quiz:555:2:A", "quiz:555:2:B", "quiz:555:2:C", "quiz:555:2:D"]


def test_build_question_view_respects_option_count():
    # Fewer options -> fewer buttons (defensive; quizzes are always 4 in practice).
    view = app.build_question_view(555, 0, ["only", "two"])
    assert len(view.children) == 2
    assert [c.custom_id for c in view.children] == ["quiz:555:0:A", "quiz:555:0:B"]
