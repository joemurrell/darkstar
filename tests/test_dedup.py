"""Tests for the dedup helpers: extract_topic, extract_keywords, similarity, dedupe."""
import app


def test_extract_topic_uses_topic_field():
    q = {"q": "irrelevant text", "topic": "Radio-Procedures"}
    assert app.extract_topic_from_question(q) == "radio-procedures"


def test_extract_topic_strips_whitespace():
    q = {"q": "irrelevant", "topic": "  fuel-system  "}
    assert app.extract_topic_from_question(q) == "fuel-system"


def test_extract_topic_falls_back_to_keywords():
    q = {"q": "How does the engine respond when fuel pressure drops critically?"}
    topic = app.extract_topic_from_question(q)
    assert topic != "unknown"
    # Top words should appear in the topic
    assert any(word in topic for word in ("engine", "fuel", "pressure", "drops", "respond"))


def test_extract_topic_unknown_when_only_stopwords():
    q = {"q": "the a an of for to be"}
    assert app.extract_topic_from_question(q) == "unknown"


def test_extract_keywords_drops_stopwords():
    keywords = app.extract_keywords("the radio frequency for tower communications")
    assert "the" not in keywords
    assert "for" not in keywords
    assert "radio" in keywords or "tower" in keywords


def test_extract_keywords_drops_short_words():
    keywords = app.extract_keywords("of to be in on")
    assert keywords == set()


def test_similar_when_topics_match():
    q1 = {"q": "Completely different question one"}
    q2 = {"q": "Totally unrelated question two"}
    assert app.are_questions_similar(q1, q2, "fuel-system", "fuel-system")


def test_similar_when_questions_nearly_identical():
    q1 = {"q": "What is the radio frequency for tower communications?"}
    q2 = {"q": "What is the radio frequency for tower communication?"}
    # Different topics on purpose; high textual similarity should still flag them
    assert app.are_questions_similar(q1, q2, "topic-a", "topic-b")


def test_not_similar_different_topic_different_content():
    q1 = {"q": "What is the standard radio frequency for tower communications?"}
    q2 = {"q": "How does engine trim affect aircraft balance during takeoff?"}
    assert not app.are_questions_similar(q1, q2, "radio-procedures", "engine-trim")


def test_deduplicate_keeps_first_of_duplicate_pairs():
    questions = [
        {"q": "Q1 about fuel", "topic": "fuel"},
        {"q": "Q2 about engines", "topic": "engine"},
        {"q": "Q3 also about fuel", "topic": "fuel"},
    ]
    unique, topics = app.deduplicate_questions(questions)
    assert len(unique) == 2
    assert topics == ["fuel", "engine"]
    assert unique[0]["q"] == "Q1 about fuel"
    assert unique[1]["q"] == "Q2 about engines"


def test_deduplicate_with_no_topics_does_not_collapse_unrelated():
    """
    Regression: previously, two questions both lacking a topic field both
    received topic 'unknown' and were treated as duplicates regardless of
    content. extract_topic_from_question should now produce distinct
    topics for distinct content.
    """
    questions = [
        {"q": "What is the radio frequency for tower communications?"},
        {"q": "How does engine trim affect aircraft balance during takeoff?"},
    ]
    unique, _ = app.deduplicate_questions(questions)
    assert len(unique) == 2


def test_deduplicate_empty_input():
    unique, topics = app.deduplicate_questions([])
    assert unique == []
    assert topics == []


def test_deduplicate_all_same_keeps_first_only():
    q = {"q": "What is the radio frequency for tower communications?", "topic": "radio"}
    unique, topics = app.deduplicate_questions([q, dict(q), dict(q)])
    assert len(unique) == 1
    assert unique[0] is q


def test_deduplicate_returns_topics_parallel_to_unique():
    questions = [
        {"q": "Q1 about altitude measurement", "topic": "altimetry"},
        {"q": "Q2 about engine performance", "topic": "engine"},
    ]
    unique, topics = app.deduplicate_questions(questions)
    assert len(unique) == len(topics)
    assert topics[0] == "altimetry"
    assert topics[1] == "engine"


# --- are_questions_similar: keyword overlap path ---

def test_similar_via_keyword_overlap_different_topics():
    # Questions that share many content words but have different explicit topics.
    # This exercises the keyword-overlap branch (line 717) rather than topic match.
    q1 = {"q": "How does fuel pressure affect engine throttle response during descent?"}
    q2 = {"q": "How does fuel pressure influence engine throttle behavior during descent?"}
    assert app.are_questions_similar(q1, q2, "fuel-system", "engine-performance")


def test_not_similar_via_keywords_disjoint_vocab():
    # Completely disjoint keyword sets → overlap/total ≤ 0.4 → not similar.
    q1 = {"q": "radio frequency tower communications clearance"}
    q2 = {"q": "fuel pressure engine throttle altitude descent"}
    assert not app.are_questions_similar(q1, q2, "radio", "fuel")
