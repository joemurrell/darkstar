"""
Test setup. app.py reads DISCORD_TOKEN, ANTHROPIC_API_KEY, and ACC_FILE_ID at
import time and raises KeyError if any is missing. Populate fake values
before any test imports the module so the import succeeds without contacting
Discord or Anthropic (clients are constructed lazily; no requests are made).
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("DISCORD_TOKEN", "test-discord-token")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")
os.environ.setdefault("ACC_FILE_ID", "file-test-id")

# Ensure the project root is importable so `import app` works regardless of
# pytest's invocation directory.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
