#!/usr/bin/env python3
"""
Demonstration script showing quiz diversity features in action.
This script shows example scenarios without requiring actual API access.
"""
import os
import sys

# Set dummy environment variables
os.environ['DISCORD_TOKEN'] = 'demo_token'
os.environ['OPENAI_API_KEY'] = 'demo_key'
os.environ['ASSISTANT_ID'] = 'demo_assistant'

from app import (
    extract_topic_from_question,
    are_questions_similar,
    deduplicate_questions
)

print("=" * 70)
print("Quiz Diversity Features - Demonstration")
print("=" * 70)

# Example 1: Topic Extraction
print("\n1. TOPIC EXTRACTION")
print("-" * 70)

questions = [
    {
        "q": "What is the procedure for PUSHING the throttle during takeoff?",
        "topic": "throttle-pushing"
    },
    {
        "q": "What is the fuel capacity of the main tank?",
        # No topic field - will be computed
    }
]

for i, q in enumerate(questions, 1):
    topic = extract_topic_from_question(q)
    print(f"Question {i}: {q['q'][:60]}...")
    if 'topic' in q:
        print(f"  → Provided topic: '{q['topic']}'")
    else:
        print(f"  → Computed topic: '{topic}'")

# Example 2: Similarity Detection
print("\n\n2. SIMILARITY DETECTION")
print("-" * 70)

similar_pairs = [
    (
        {"q": "What is the correct procedure for PUSHING the throttle?"},
        {"q": "How do you perform PUSHING on the throttle correctly?"},
        "throttle-pushing",
        "throttle-pushing"
    ),
    (
        {"q": "What is FUMBLE recovery procedure during emergency?"},
        {"q": "Steps for emergency FUMBLE situation handling?"},
        "fumble-recovery",
        "fumble-emergency"
    ),
    (
        {"q": "What is the fuel capacity?"},
        {"q": "What is the maximum altitude?"},
        "fuel-capacity",
        "altitude-limits"
    )
]

for i, (q1, q2, t1, t2) in enumerate(similar_pairs, 1):
    similar = are_questions_similar(q1, q2, t1, t2)
    print(f"\nPair {i}:")
    print(f"  Q1: {q1['q'][:50]}...")
    print(f"      Topic: '{t1}'")
    print(f"  Q2: {q2['q'][:50]}...")
    print(f"      Topic: '{t2}'")
    print(f"  → Similar: {'YES ⚠️' if similar else 'NO ✓'}")

# Example 3: Deduplication in Action
print("\n\n3. DEDUPLICATION IN ACTION")
print("-" * 70)

print("\nOriginal question set (with duplicates):")
duplicate_questions = [
    {
        "q": "What is the procedure for PUSHING the throttle during takeoff?",
        "options": ["A", "B", "C", "D"],
        "answer": "A",
        "explain": "Test (p.10)",
        "topic": "throttle-pushing"
    },
    {
        "q": "How do you perform PUSHING on the throttle correctly?",
        "options": ["A", "B", "C", "D"],
        "answer": "B",
        "explain": "Test (p.11)",
        "topic": "throttle-pushing"
    },
    {
        "q": "What is FUMBLE recovery procedure during emergency?",
        "options": ["A", "B", "C", "D"],
        "answer": "C",
        "explain": "Test (p.20)",
        "topic": "fumble-recovery"
    },
    {
        "q": "Steps for emergency FUMBLE situation handling?",
        "options": ["A", "B", "C", "D"],
        "answer": "D",
        "explain": "Test (p.21)",
        "topic": "fumble-recovery"
    },
    {
        "q": "What is the fuel capacity of the main tank?",
        "options": ["A", "B", "C", "D"],
        "answer": "A",
        "explain": "Test (p.30)",
        "topic": "fuel-capacity"
    },
    {
        "q": "What is the maximum altitude for combat operations?",
        "options": ["A", "B", "C", "D"],
        "answer": "B",
        "explain": "Test (p.40)",
        "topic": "altitude-limits"
    }
]

for i, q in enumerate(duplicate_questions, 1):
    print(f"  {i}. [{q['topic']}] {q['q'][:55]}...")

unique, topics = deduplicate_questions(duplicate_questions)

print(f"\n→ Original count: {len(duplicate_questions)}")
print(f"→ After deduplication: {len(unique)} unique questions")
print(f"→ Removed: {len(duplicate_questions) - len(unique)} duplicates")

print("\nUnique questions retained:")
for i, (q, topic) in enumerate(zip(unique, topics), 1):
    print(f"  {i}. [{topic}] {q['q'][:55]}...")

print("\n" + "=" * 70)
print("Demonstration complete!")
print("=" * 70)
print("\nKey Features:")
print("  ✓ Topics extracted from question field or computed from text")
print("  ✓ Similarity detected via exact topic match, fuzzy text match, or keyword overlap")
print("  ✓ Duplicates automatically removed before returning quiz")
print("  ✓ Regeneration triggered when unique count < requested count")
print("  ✓ All interactions logged to logs/ai_replies.log")
print("\nRun 'python run_tests.py' to execute the full test suite.")
print("=" * 70)
