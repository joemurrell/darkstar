# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

DarkstarAIC is a single-file Discord bot (`app.py`) that provides PDF-grounded Q&A and timed multiple-choice quizzes for the DCS Air Control Communication community. It uses the Anthropic Claude API (`AsyncAnthropic`) with the ACC documentation embedded as cached plain text in the system prompt, prompt caching for cost, and tool-use for structured quiz output. Deployed on Railway via Docker.

The PDF is sent as extracted **plain text**, not an Anthropic `document` block. PDFs sent as documents incur per-page *image* tokens on top of the text, and that combined size pushed a single request past the Tier 1 50,000-input-token-per-minute limit. Plain text is leaner and keeps the cold-cache write under the ceiling.

## Running

Four environment variables are required and the bot will crash on startup without them:

- `DISCORD_TOKEN` — Discord bot token
- `ANTHROPIC_API_KEY` — Anthropic API key
- `CLAUDE_MODEL` — optional, defaults to `claude-haiku-4-5`. Bump to `claude-sonnet-4-6` for higher-quality quiz generation (~6× the cost).
- `ACC_DOCUMENT_PATH` — optional, defaults to `acc_document.txt`. The extracted ACC text the bot loads at startup (see "Extracting the PDF" below). Not an env requirement, but the file must exist or the bot runs ungrounded.
- `DARKSTAR_DB_PATH` — optional, defaults to `darkstar.db`. SQLite file for quiz persistence. **On Railway, point this at a mounted volume** (e.g. `/data/darkstar.db`) or the DB is ephemeral and in-flight quizzes still vanish on redeploy.

```bash
pip install -r requirements.txt
python app.py
```

Docker (matches Railway production):

```bash
docker build -t darkstar .
docker run --rm \
  -e DISCORD_TOKEN=... -e ANTHROPIC_API_KEY=... \
  darkstar
```

### Extracting the PDF

`scripts/extract_pdf.py` is a one-time helper. It extracts the PDF to plain text and (if `ANTHROPIC_API_KEY` is set) prints the exact Claude token count so you can confirm the document fits under your tier's per-minute input-token limit before deploying:

```bash
pip install -r requirements-dev.txt   # provides pypdf
export ANTHROPIC_API_KEY=...          # optional, enables the token-count check
python scripts/extract_pdf.py path/to/acc_2024.pdf
```

It writes `acc_document.txt` in the repo root — **commit that file**; the bot loads it at startup. Re-run only when the source PDF changes. `pypdf` is a dev-only dependency (the bot just reads the `.txt` at runtime). The Dockerfile copies `acc_document.txt` into the image.

### Tests + lint

```bash
pip install -r requirements-dev.txt
ruff check .
pytest                       # all tests
pytest tests/test_dedup.py   # one file
pytest -k "shuffle"          # one test by keyword
```

Tests live in `tests/` and cover the pure helpers — `validate_quiz_questions`, `shuffle_quiz_options`, the dedup chain, and the small Discord helpers. They import `app` directly; `tests/conftest.py` populates fake env vars so the import succeeds without contacting Discord or Anthropic. The Discord/Anthropic clients in `app.py` are constructed lazily and make no requests until called, so tests don't need to mock them.

CI lives at `.github/workflows/ci.yml` and runs ruff + pytest on push to main and on every PR.

## Architecture

### Single-file layout (`app.py`)

Roughly in file order:

1. **Environment + Anthropic client + logging setup** (top of file)
2. **`ACC_INSTRUCTIONS`** — the system prompt as a module-level constant. Edit directly and redeploy to change tone or refusal behavior.
3. **UI components** — `QuizAnswerButton`, `QuizQuestionView` (Discord buttons)
4. **`check_bot_permissions`** — every slash command calls this first; produces verbose diagnostic strings when perms are missing
5. **`ask_assistant`** — the Claude integration layer (handles both plain text and forced tool-use)
6. **Quiz pipeline** — `format_mcq`, `shuffle_quiz_options`, dedup helpers, `QUIZ_TOOL`, `validate_quiz_questions`, `_request_quiz_questions`, `generate_quiz`, `auto_end_quiz`, `display_quiz_results`
7. **Slash commands** — `/ask`, `/quiz_start`, `/quiz_answer`, `/quiz_end`, `/quiz_score`, `/info`
8. **`on_ready` + `client.run()`**

### PDF grounding via the Files API

The ACC PDF is uploaded once to Anthropic (see "Uploading the PDF") and referenced by `file_id` in every request. `ask_assistant` builds a request with:

- `system`: `ACC_INSTRUCTIONS` (cached)
- `messages[0].content`: `[document(file_id=ACC_FILE_ID, cache_control=ephemeral), text(user_msg)]`
- `betas=["files-api-2025-04-14"]` to enable the Files API beta

Both the system prompt and the document block are marked `cache_control: {"type": "ephemeral"}` so the ~50K-token prefix is served from cache (~10% of base input price) on every request after the first one in a 5-minute window. The varying user question lands *after* the document block, so it doesn't invalidate the cached prefix.

Verify caching is working by inspecting `usage.cache_read_input_tokens` in the logs — if it's zero across repeated requests, something is invalidating the prefix (likely an interpolated date or user-id into `ACC_INSTRUCTIONS`).

### Quiz state + persistence

`QUIZ_STATE: dict[int, dict]` is a module-level dict keyed by Discord `channel_id` and is the **hot-path source of truth** (button clicks, timers). Each entry holds the question list (shuffled), per-user answers (`{str(user_id): {int position: choice}}`), end time, duration, initiator user ID, the `quiz_id` of its DB row, and the `auto_end_quiz` task handle.

`db.py` (`QuizStore`, aiosqlite) **mirrors** this to SQLite so quizzes survive a restart. Persistence is **best-effort**: `quiz_start` persists on creation (`create_quiz`), the answer paths call `_persist_answer`, and `display_quiz_results` calls `_persist_completion` — every one wrapped so a storage failure degrades to in-memory-only rather than breaking a live quiz (`quiz_id` stays `None` and the mirror calls no-op). Schema: `quizzes` (surrogate id, `status` active/completed, partial unique index enforcing one *active* quiz per channel), `quiz_questions`, `quiz_answers` (upsert PK). See `tests/test_db.py`.

On startup, `on_ready` opens the store **once** (guarded by `_startup_done`) and calls `rehydrate_quizzes`: each active quiz is restored into `QUIZ_STATE` and its `auto_end_quiz` timer re-armed for the *remaining* time; a quiz that expired during downtime is finalized immediately. **Caveat:** buttons on messages posted before a restart won't respond (their `View` objects died with the process) — `/quiz_answer` is the fallback, and recorded answers are preserved regardless. Re-registering persistent views would need channel-scoped `custom_id`s (a follow-up).

`auto_end_quiz` derives its sleep from `state["end_time"]` (not a fixed duration), so both fresh and rehydrated quizzes end at the right wall-clock time. Its task handle is stored in `state["end_task"]` to keep it from being GC'd and so `display_quiz_results` can cancel it on manual `/quiz_end`; the cancel path skips itself when invoked from inside the auto-end task to avoid `CancelledError` on self.

### Quiz generation pipeline

`generate_quiz` uses forced tool-use against `QUIZ_TOOL`:

1. Build a prompt asking for N MCQs.
2. Call `ask_assistant(prompt, tool=QUIZ_TOOL, temperature=0.7)`. The `tool_choice` is set to force `submit_quiz`, so Claude must call it.
3. Claude's response contains a `tool_use` block whose `input` is the parsed dict — no JSON-string parsing, no fence-stripping needed.
4. `validate_quiz_questions` filters to items with exactly 4 options and a valid answer letter (defense in depth — the schema enforces this on Claude's side too).
5. Run `deduplicate_questions` (see below).
6. If under target count, regenerate up to 3 times at `temperature=0.8` with an "exclude these topics" prompt.
7. Shuffle each question's options via `shuffle_quiz_options` (re-letters the correct answer, preserves every other field).

### Deduplication

Three signals in `are_questions_similar`:

1. **Exact topic-tag match** — short-circuits to `True`. Because `QUIZ_TOOL`'s `input_schema` makes `topic` required, this cannot collapse multiple "unknown" questions into one.
2. Fuzzy text ratio > 85% via `difflib.SequenceMatcher`
3. Top-5 keyword overlap > 40% (after stopword removal)

If you touch the schema and remove the `topic` requirement, restore the validation guard before relying on the dedup logic — they're coupled.

### Response handling in `ask_assistant`

`ask_assistant` accepts an optional `tool` dict. When provided:

- The request includes `tools=[tool]` and `tool_choice={"type": "tool", "name": tool["name"]}`.
- The return value is the `tool_use.input` dict, not a string.
- Returns `None` (instead of an error string) on refusal / timeout so the caller can branch cleanly.

When `tool` is omitted, the return value is a plain text string (the concatenation of all `text` blocks in `response.content`). The `refusal` stop reason is handled explicitly with a user-friendly message.

Token-usage details (input, cache-read, cache-write, output) are logged on every successful response.

### Permissions

`check_bot_permissions` builds a multi-line diagnostic string by walking `@everyone`, each bot role, and any member-specific overwrite. It checks `send_messages`, `embed_links`, `read_message_history`, `view_channel`, and `use_application_commands`. The final message is truncated at 1900 chars to stay inside Discord's 2000-char interaction limit. DMs short-circuit to "ok".

### Discord limit helpers

Three small helpers near `format_mcq` exist to keep Discord output inside platform limits:

- `format_time_remaining(end_time)` — `(minutes, seconds)` bounded at 0, used everywhere the bot displays a countdown
- `truncate_for_discord(text, limit=2000)` — closes any open triple-backtick fence before truncating so markdown stays well-formed
- `chunk_mentions(user_ids, base_name)` — packs `<@id>` strings into 1024-char embed-field-value chunks; paginates field name as `"<base> (1/2)"` etc. when needed

If you display user mentions or LLM-generated prose, route through these rather than building strings inline.

### Logging

Four named loggers — `__main__`, `discord_bot`, `quiz`, `anthropic_api` — all to stdout (Railway captures stdout). Format includes `funcName:lineno`. Debug-level logs include raw user answer dicts. The API logger emits token-usage breakdowns (input / cache-read / cache-write / output) on every Claude response so you can verify caching is hitting.

## Slash command sync

`tree.sync()` runs on every `on_ready` and is **global** (no `guild=` arg). Global syncs are rate-limited and can take up to an hour to propagate. For dev work, register to a specific guild instead.

## Deployment notes

- `Dockerfile` runs as non-root `appuser` (uid 1000) and sets `MALLOC_ARENA_MAX=2` to reduce glibc fragmentation
- `railway.json` configures `ON_FAILURE` restart with up to 10 retries — combined with in-memory quiz state, this means a flaky deploy can silently wipe active quizzes multiple times
- `h11==0.16.0` is pinned in `requirements.txt` for a security fix; if you bump `discord.py` or `anthropic`, verify `h11` compatibility
