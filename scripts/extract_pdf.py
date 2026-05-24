"""
One-time helper to extract the ACC reference PDF to plain text for embedding
in the bot's cached system prompt.

Sending the PDF as plain text (rather than as an Anthropic `document` block)
avoids the per-page image tokens Claude adds for PDFs — those image tokens are
what pushed a single request past the Tier 1 50,000-input-token-per-minute
limit. Plain text is leaner and keeps the cold-cache write under the ceiling.

Usage:
    pip install -r requirements-dev.txt   # provides pypdf
    export ANTHROPIC_API_KEY=...          # optional, enables the token-count check
    python scripts/extract_pdf.py path/to/acc_2024.pdf

Writes acc_document.txt in the repo root (override with a second arg) and, if
ANTHROPIC_API_KEY is set, prints the exact Claude token count so you can
confirm it fits under your tier's per-minute input-token limit before
deploying. Commit acc_document.txt — the bot loads it at startup.
"""
import os
import sys
from pathlib import Path

from pypdf import PdfReader

DEFAULT_OUT = "acc_document.txt"
# Comfortable ceiling under the Tier 1 50K ITPM limit, leaving room for the
# system prompt + tool schema + the user's question.
TIER1_WARN_THRESHOLD = 45_000


def main() -> int:
    if len(sys.argv) not in (2, 3):
        print(__doc__, file=sys.stderr)
        return 2

    pdf_path = Path(sys.argv[1])
    out_path = Path(sys.argv[2]) if len(sys.argv) == 3 else Path(DEFAULT_OUT)

    if not pdf_path.is_file():
        print(f"ERROR: {pdf_path} is not a file", file=sys.stderr)
        return 1

    reader = PdfReader(str(pdf_path))
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    out_path.write_text(text, encoding="utf-8")

    print(f"Extracted {len(reader.pages)} pages -> {out_path}")
    print(f"  characters: {len(text):,}")

    # Report the exact Claude token count so the fit is verifiable up front.
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("  (set ANTHROPIC_API_KEY to print the exact Claude token count)")
        return 0

    from anthropic import Anthropic

    client = Anthropic(api_key=api_key)
    count = client.messages.count_tokens(
        model=os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5"),
        system=text,
        messages=[{"role": "user", "content": "x"}],
    )
    tokens = count.input_tokens
    print(f"  Claude tokens: {tokens:,}")
    if tokens > TIER1_WARN_THRESHOLD:
        print(
            f"  ⚠️  {tokens:,} tokens is close to / over the Tier 1 50,000 ITPM "
            f"ceiling once the tool schema and question are added. Expect 429s "
            f"on Tier 1 — consider upgrading to Tier 2 (450K ITPM)."
        )
    else:
        print("  ✓ Comfortably under the Tier 1 50,000 ITPM ceiling.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
