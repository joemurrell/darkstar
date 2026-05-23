# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

DarkstarAIC is a single-file Discord bot (`app.py`) that provides PDF-grounded Q&A and timed multiple-choice quizzes for the DCS Air Control Communication community. It uses the OpenAI Responses API (via `AsyncOpenAI`) with a `file_search` tool backed by a vector store. Deployed on Railway via Docker.

## Running

Three environment variables are required and the bot will crash on startup without them:

- `DISCORD_TOKEN` — Discord bot token
- `OPENAI_API_KEY` — OpenAI API key
- `ASSISTANT_ID` — an existing OpenAI Assistant (still required even though the bot uses the Responses API; see "Assistant config bootstrap" below)

```bash
pip install -r requirements.txt
python app.py
```

Docker (matches Railway production):

```bash
docker build -t darkstar .
docker run --rm \
  -e DISCORD_TOKEN=... -e OPENAI_API_KEY=... -e ASSISTANT_ID=... \
  darkstar
```

### Tests + lint

```bash
pip install -r requirements-dev.txt
ruff check .
pytest                       # all tests
pytest tests/test_dedup.py   # one file
pytest -k "shuffle"          # one test by keyword
```

Tests live in `tests/` and cover the pure helpers — `parse_quiz_response`, `validate_quiz_questions`, `shuffle_quiz_options`, the dedup chain, and the small Discord/OpenAI helpers. They import `app` directly; `tests/conftest.py` populates fake env vars so the import succeeds without contacting Discord or OpenAI. The Discord/OpenAI clients in `app.py` are constructed lazily and make no requests until called, so tests don't need to mock them.

CI lives at `.github/workflows/ci.yml` and runs ruff + pytest on push to main and on every PR. Ruff config in `pyproject.toml` is intentionally conservative (`select = ["F", "E9", "W6"]`) so existing code passes without a style sweep; expand to `E/W/B/UP/I` in a follow-up.

## Architecture

### Single-file layout (`app.py`)

Roughly in file order:

1. **Environment + OpenAI client + logging setup** (top of file)
2. **UI components** — `QuizAnswerButton`, `QuizQuestionView` (Discord buttons)
3. **`check_bot_permissions`** — every slash command calls this first; produces verbose diagnostic strings when perms are missing
4. **`initialize_assistant_config` + `ask_assistant`** — the OpenAI integration layer
5. **Quiz pipeline** — `format_mcq`, `shuffle_quiz_options`, dedup helpers, `generate_quiz`, `auto_end_quiz`, `display_quiz_results`
6. **Slash commands** — `/ask`, `/quiz_start`, `/quiz_answer`, `/quiz_end`, `/quiz_score`, `/info`
7. **`on_ready` + `client.run()`**

### Assistant config bootstrap

The bot was migrated from the Assistants API to the Responses API (see `MIGRATION_NOTES.md`), but it still uses `oai.beta.assistants.retrieve(ASSISTANT_ID)` at startup to read the assistant's `instructions`, `model`, and `vector_store_ids`. Those are cached in the module-level `ASSISTANT_CONFIG` dict and used to build every Responses API request. **Before `on_ready` completes, `ASSISTANT_CONFIG` values are all `None`** — any code path that runs before bot startup will see empty config.

### Quiz state

`QUIZ_STATE: dict[int, dict]` is a module-level dict keyed by Discord `channel_id`. Each entry holds the question list (shuffled), per-user answers, end time, duration, initiator user ID, and the `auto_end_quiz` task handle.

**This is in-memory only.** Any process restart (deploy, Railway OOM, crash) wipes all in-flight quizzes with no recovery. Only one quiz per channel at a time.

`auto_end_quiz` is scheduled via `asyncio.create_task(...)` at quiz start; the task handle is stored in `state["end_task"]` to keep it from being GC'd and so `display_quiz_results` can cancel it on manual `/quiz_end`. The cancel path skips itself when invoked from inside the auto-end task to avoid `CancelledError` on self.

### Quiz generation pipeline

`generate_quiz` is the most complex function. The flow:

1. Build prompt asking for N MCQs covering distinct topics
2. Call `ask_assistant` with `temperature=0.7` and `response_format=QUIZ_RESPONSE_FORMAT` (strict json_schema requiring `q`, `options`, `answer` ∈ {A,B,C,D}, `explain`, `page`, `topic`)
3. `parse_quiz_response` extracts the `questions` array (with permissive ```` ```json ```` fence stripping as a fallback)
4. `validate_quiz_questions` filters to items with exactly 4 options and a valid answer letter
5. Run `deduplicate_questions` (see below)
6. If under target count, regenerate up to 3 times at `temperature=0.8` with an "exclude these topics" prompt (also schema-constrained)
7. Shuffle each question's options via `shuffle_quiz_options` (re-letters the correct answer, preserves every other field)

### Deduplication

Three signals in `are_questions_similar`:

1. **Exact topic-tag match** — short-circuits to `True`. Because `QUIZ_RESPONSE_FORMAT` makes `topic` required, this no longer collapses multiple "unknown" questions into one (the previous behavior).
2. Fuzzy text ratio > 85% via `difflib.SequenceMatcher`
3. Top-5 keyword overlap > 40% (after stopword removal)

If you touch the schema and remove the `topic` requirement, restore the validation guard before relying on the dedup logic — they're coupled.

### Response parsing in `ask_assistant`

Citation markers like `【4:2†source】` are stripped via regex before returning. The code iterates every item in `response.output` looking for `message` types and skips tool-call items (e.g. `file_search_call`), so a tool-call landing before the message no longer swallows the response.

`ask_assistant` also accepts a `response_format` dict that gets wired into the Responses-API `text.format` slot for structured outputs. Pass `model_supports_temperature(model)` is consulted before sending `temperature` — reasoning models (o1/o3/o4) and the gpt-5 family reject it.

### Permissions

`check_bot_permissions` builds a multi-line diagnostic string by walking `@everyone`, each bot role, and any member-specific overwrite. It checks `send_messages`, `embed_links`, `read_message_history`, `view_channel`, and `use_application_commands`. The final message is truncated at 1900 chars to stay inside Discord's 2000-char interaction limit. DMs short-circuit to "ok".

### Discord limit helpers

Three small helpers near `format_mcq` exist to keep Discord output inside platform limits:

- `format_time_remaining(end_time)` — `(minutes, seconds)` bounded at 0, used everywhere the bot displays a countdown
- `truncate_for_discord(text, limit=2000)` — closes any open triple-backtick fence before truncating so markdown stays well-formed
- `chunk_mentions(user_ids, base_name)` — packs `<@id>` strings into 1024-char embed-field-value chunks; paginates field name as `"<base> (1/2)"` etc. when needed

If you display user mentions or LLM-generated prose, route through these rather than building strings inline.

### Logging

Four named loggers — `__main__`, `discord_bot`, `quiz`, `openai_api` — all to stdout (Railway captures stdout). Format includes `funcName:lineno`. Debug-level logs include raw user answer dicts.

## Slash command sync

`tree.sync()` runs on every `on_ready` and is **global** (no `guild=` arg). Global syncs are rate-limited and can take up to an hour to propagate. For dev work, register to a specific guild instead.

## Deployment notes

- `Dockerfile` runs as non-root `appuser` (uid 1000) and sets `MALLOC_ARENA_MAX=2` to reduce glibc fragmentation
- `railway.json` configures `ON_FAILURE` restart with up to 10 retries — combined with in-memory quiz state, this means a flaky deploy can silently wipe active quizzes multiple times
- `h11==0.16.0` is pinned in `requirements.txt` for a security fix; if you bump `discord.py` or `openai`, verify `h11` compatibility
