"""
One-time helper to upload the ACC reference PDF to Anthropic's Files API.

Usage:
    pip install anthropic
    export ANTHROPIC_API_KEY=...
    python scripts/upload_pdf.py path/to/acc_2024.pdf

Prints the file_id — set as ACC_FILE_ID on Railway. The file persists on
Anthropic's side until you delete it; re-running creates a duplicate.
"""
import sys
from pathlib import Path

from anthropic import Anthropic


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2

    pdf_path = Path(sys.argv[1])
    if not pdf_path.is_file():
        print(f"ERROR: {pdf_path} is not a file", file=sys.stderr)
        return 1

    client = Anthropic()  # reads ANTHROPIC_API_KEY from env

    with pdf_path.open("rb") as fh:
        uploaded = client.beta.files.upload(
            file=(pdf_path.name, fh, "application/pdf"),
        )

    print(f"Uploaded {pdf_path.name}")
    print(f"  file_id:   {uploaded.id}")
    print(f"  size:      {uploaded.size_bytes:,} bytes")
    print()
    print("Set this on Railway:")
    print(f"  ACC_FILE_ID={uploaded.id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
