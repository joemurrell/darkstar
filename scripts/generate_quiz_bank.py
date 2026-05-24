"""
One-time helper to generate the question bank the bot serves quizzes from.

/quiz_start samples questions out of acc_questions.json instead of calling
Claude on every quiz, so quizzes become instant and free. This script builds
that pool: it asks Claude (grounded in the same cached ACC documentation the
bot uses) for batches of multiple-choice questions, deduplicates them across
the whole run, and writes the result as a JSON list of question dicts.

Run it once, then commit acc_questions.json. Re-run it only when the ACC
document changes (regenerate acc_document.txt with extract_pdf.py first).

Usage:
    pip install -r requirements-dev.txt
    export ANTHROPIC_API_KEY=...                 # required (spends against your account)
    # optional: a bigger model makes a higher-quality bank for a one-time cost
    export CLAUDE_MODEL=claude-sonnet-4-6
    python scripts/generate_quiz_bank.py --count 120

The bank stores questions with their original answer letter; the bot reshuffles
options at quiz time, so the same banked question still varies between quizzes.
"""
import argparse
import asyncio
import json
import os
import random
import sys
from pathlib import Path

DEFAULT_OUT = "acc_questions.json"


def build_prompt(batch_size: int, known_topics: list) -> str:
    """Prompt for one batch, steering Claude away from already-covered topics."""
    exclusion = ""
    if known_topics:
        # Cap the exclusion list so the (uncached) prompt suffix stays small;
        # a random sample keeps later batches from always excluding the same set.
        sample = known_topics if len(known_topics) <= 60 else random.sample(known_topics, 60)
        exclusion = (
            "\n\nDo NOT repeat any of these already-covered topics — choose fresh, "
            "distinct concepts:\n" + ", ".join(sorted(sample))
        )
    return (
        f"Generate {batch_size} multiple-choice questions based ONLY on the ACC documentation.\n\n"
        "Requirements:\n"
        "- Each question must have exactly 4 options\n"
        "- Provide a brief explanation with a page reference like (p.XX) in `explain`\n"
        "- Set `page` to the integer page number from the PDF\n"
        "- Set `topic` to a short hyphenated tag identifying the concept (e.g. \"fuel-system\")\n"
        "- Focus on practical knowledge for DCS pilots and air controllers\n"
        "- Vary difficulty and draw from many different sections of the document\n"
        "- Every question must cover a different topic from the others; do not repeat distinctive keywords"
        + exclusion
        + "\n\nCall the submit_quiz tool with your questions."
    )


async def build_bank(app, count: int, batch_size: int, max_dry_streak: int) -> list:
    pool: list = []
    topics: list = []
    dry_streak = 0
    attempt = 0

    while len(pool) < count:
        attempt += 1
        prompt = build_prompt(batch_size, topics)
        questions = await app._request_quiz_questions(prompt, temperature=0.9)

        added = 0
        for q in questions:
            topic = app.extract_topic_from_question(q)
            if any(
                app.are_questions_similar(q, existing_q, topic, existing_topic)
                for existing_q, existing_topic in zip(pool, topics)
            ):
                continue
            pool.append(q)
            topics.append(topic)
            added += 1
            if len(pool) >= count:
                break

        print(f"  attempt {attempt}: +{added} new (total {len(pool)}/{count})")

        # Stop if the document is saturated — several batches in a row that add
        # nothing new mean we've covered what's there.
        dry_streak = dry_streak + 1 if added == 0 else 0
        if dry_streak >= max_dry_streak:
            print(
                f"  no new questions in {max_dry_streak} consecutive attempts — "
                f"stopping (the document appears saturated at {len(pool)} questions)"
            )
            break

    return pool


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the bot's quiz question bank.")
    parser.add_argument("--count", type=int, default=120, help="target number of questions (default 120)")
    parser.add_argument("--out", default=DEFAULT_OUT, help=f"output path (default {DEFAULT_OUT})")
    parser.add_argument("--batch", type=int, default=10, help="questions requested per API call (default 10)")
    parser.add_argument(
        "--max-dry-streak", type=int, default=5,
        help="stop after this many consecutive batches that add nothing new (default 5)",
    )
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY must be set (this script spends against your account).", file=sys.stderr)
        return 1
    # app.py reads DISCORD_TOKEN at import but never connects here; a placeholder
    # is enough to import it and reuse its grounded generation pipeline.
    os.environ.setdefault("DISCORD_TOKEN", "quiz-bank-generator-not-a-bot")

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import app  # noqa: E402  (import after env is set up, like tests/conftest.py)

    if not app.ACC_DOCUMENT_TEXT.strip():
        print(
            f"ERROR: ACC document is empty (expected at {app.ACC_DOCUMENT_PATH}). "
            f"Run scripts/extract_pdf.py and commit acc_document.txt first.",
            file=sys.stderr,
        )
        return 1

    print(f"Generating ~{args.count} questions with {app.CLAUDE_MODEL} (batch {args.batch})...")
    pool = asyncio.run(build_bank(app, args.count, args.batch, args.max_dry_streak))

    if not pool:
        print("ERROR: generated no questions.", file=sys.stderr)
        return 1

    out_path = Path(args.out)
    out_path.write_text(json.dumps(pool, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    distinct_topics = sorted({(q.get("topic") or "").lower() for q in pool})
    print(f"\nWrote {len(pool)} questions -> {out_path}")
    print(f"  distinct topics: {len(distinct_topics)}")
    print("  Commit this file — the bot loads it at startup.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
