"""Tests for format_mcq: Discord embed formatting for multiple-choice questions."""
import app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _embed(question="What is X?", options=None, **kwargs):
    if options is None:
        options = ["opt_a", "opt_b", "opt_c", "opt_d"]
    return app.format_mcq(question, options, **kwargs)


def _field_value(embed):
    """Return the single options field value from a format_mcq embed."""
    return embed.fields[0].value


# ---------------------------------------------------------------------------
# Basic structure
# ---------------------------------------------------------------------------

def test_returns_discord_embed():
    import discord
    embed = _embed()
    assert isinstance(embed, discord.Embed)


def test_embed_has_exactly_one_field():
    assert len(_embed().fields) == 1


def test_embed_color_is_forest_green():
    assert _embed().color.value == 0x2D5016


def test_description_contains_question_text():
    embed = _embed(question="How does fuel pressure affect engine output?")
    assert "How does fuel pressure affect engine output?" in embed.description


def test_description_wraps_question_in_bold():
    embed = _embed(question="Which frequency is used?")
    assert "**Which frequency is used?**" in embed.description


# ---------------------------------------------------------------------------
# Question numbering
# ---------------------------------------------------------------------------

def test_without_question_num_no_numbering_header():
    embed = _embed()
    assert "Question" not in embed.description


def test_with_question_num_shows_progress():
    embed = _embed(question="What is X?", question_num=3, total=10)
    assert "Question 3/10" in embed.description
    assert "**What is X?**" in embed.description


def test_with_question_num_question_text_still_bold():
    embed = _embed(question="Q text", question_num=1, total=5)
    assert "**Q text**" in embed.description


def test_with_question_num_one_only_no_numbering():
    # question_num without total → no numbering (both must be provided)
    embed = _embed(question_num=1)
    assert "Question" not in embed.description


def test_with_total_only_no_numbering():
    # total without question_num → no numbering (both must be provided)
    embed = _embed(total=5)
    assert "Question" not in embed.description


# ---------------------------------------------------------------------------
# Option labels
# ---------------------------------------------------------------------------

def test_four_options_labeled_a_through_d():
    value = _field_value(_embed(options=["w", "x", "y", "z"]))
    for letter in ["A", "B", "C", "D"]:
        assert f"**{letter})**" in value


def test_two_options_labeled_a_and_b_only():
    embed = app.format_mcq("Q?", ["alpha", "beta"])
    value = _field_value(embed)
    assert "**A)**" in value
    assert "**B)**" in value
    assert "**C)**" not in value


def test_option_text_appears_in_field():
    embed = app.format_mcq("Q?", ["apple", "banana", "cherry", "date"])
    value = _field_value(embed)
    for word in ["apple", "banana", "cherry", "date"]:
        assert word in value


# ---------------------------------------------------------------------------
# Option prefix stripping
# ---------------------------------------------------------------------------

def test_strips_paren_prefix():
    embed = app.format_mcq("Q?", ["A) first", "B) second", "C) third", "D) fourth"])
    value = _field_value(embed)
    assert "first" in value
    assert "A) first" not in value


def test_strips_dot_prefix():
    embed = app.format_mcq("Q?", ["A. alpha", "B. bravo", "C. charlie", "D. delta"])
    value = _field_value(embed)
    assert "alpha" in value
    assert "A. alpha" not in value


def test_strips_colon_prefix():
    embed = app.format_mcq("Q?", ["A: one", "B: two", "C: three", "D: four"])
    value = _field_value(embed)
    assert "one" in value
    assert "A: one" not in value


def test_strips_dash_prefix():
    embed = app.format_mcq("Q?", ["A- foo", "B- bar", "C- baz", "D- qux"])
    value = _field_value(embed)
    assert "foo" in value
    assert "A- foo" not in value


def test_strips_space_separator_prefix():
    embed = app.format_mcq("Q?", ["A foo", "B bar", "C baz", "D qux"])
    value = _field_value(embed)
    assert "foo" in value
    assert "A foo" not in value


def test_strips_leading_whitespace_before_prefix():
    embed = app.format_mcq("Q?", ["  A) indented", "B) normal", "C) normal", "D) normal"])
    value = _field_value(embed)
    assert "indented" in value
    assert "A) indented" not in value


def test_strips_extra_spaces_after_separator():
    embed = app.format_mcq("Q?", ["A)   spaced", "B) b", "C) c", "D) d"])
    value = _field_value(embed)
    assert "spaced" in value
    # The double/triple space should be collapsed by stripping inside the function
    assert "   spaced" not in value


def test_no_stripping_when_second_char_not_separator():
    # "Apple" — second char 'p' is not in ').:- '
    embed = app.format_mcq("Q?", ["Apple", "Banana", "Cherry", "Durian"])
    value = _field_value(embed)
    assert "Apple" in value
    assert "Banana" in value


def test_no_stripping_for_lowercase_starting_options():
    embed = app.format_mcq("Q?", ["at least", "by contrast", "certain", "during"])
    value = _field_value(embed)
    assert "at least" in value


def test_lowercase_letter_prefix_also_stripped():
    # 'a)' → lower-case: cleaned[0].upper() in 'ABCDEF' covers this
    embed = app.format_mcq("Q?", ["a) lower-a", "b) lower-b", "c) lower-c", "d) lower-d"])
    value = _field_value(embed)
    assert "lower-a" in value
    assert "a) lower-a" not in value
