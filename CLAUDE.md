# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

DarkstarAIC is a single-file Discord bot (`app.py`) that provides PDF-grounded Q&A and timed multiple-choice quizzes for the DCS Air Control Communication community. It uses the OpenAI Responses API with a `file_search` tool backed by a vector store. Deployed on Railway via Docker.

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

There are currently **no tests, no linter config, and no CI** beyond Dependabot.

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

`QUIZ_STATE: dict[int, dict]` is a module-level dict keyed by Discord `channel_id`. Each entry holds the question list (shuffled), per-user answers, end time, duration, and initiator user ID.

**This is in-memory only.** Any process restart (deploy, Railway OOM, crash) wipes all in-flight quizzes with no recovery. Only one quiz per channel at a time.

`auto_end_quiz` is scheduled via `asyncio.create_task(...)` at quiz start; the task reference is **not stored**, and is not cancelled on `/quiz_end`. Long quizzes leave orphan sleep tasks alive until their timer fires.

### Quiz generation pipeline

`generate_quiz` is the most complex function. The flow:

1. Build prompt asking for N MCQs with `q`, `options`, `answer`, `explain`, `topic`, `page` fields
2. Call `ask_assistant` with `temperature=0.7`
3. Strip ```` ```json ```` fences, parse JSON
4. Validate (require `q`/`options`/`answer`/`explain` only — `topic` and `page` are **not** enforced)
5. Run `deduplicate_questions` (see below)
6. If under target count, regenerate up to 3 times with an "exclude these topics" prompt at `temperature=0.8`
7. Shuffle each question's options via `shuffle_quiz_options` (re-letters the correct answer)

### Deduplication

Three signals in `are_questions_similar`:

1. **Exact topic-tag match** — short-circuits to `True`. Combined with `extract_topic_from_question` returning `"unknown"` when the `topic` field is missing, this means **any two questions both lacking `topic` collapse to one**.
2. Fuzzy text ratio > 85% via `difflib.SequenceMatcher`
3. Top-5 keyword overlap > 40% (after stopword removal)

If you touch this logic, also update the topic-field validation in `generate_quiz` — they're coupled.

### Response parsing in `ask_assistant`

Citation markers like `【4:2†source】` are stripped via regex before returning. Only `response.output[0]` is inspected for the `message` type — when `file_search` actually fires, the first output item may be a `file_search_call` and the message will be silently skipped.

### Permissions

`check_bot_permissions` builds a multi-line diagnostic string by walking `@everyone`, each bot role, and any member-specific overwrite. It does **not** check the `applications.commands` scope. DMs short-circuit to "ok".

### Logging

Four named loggers — `__main__`, `discord_bot`, `quiz`, `openai_api` — all to stdout (Railway captures stdout). Format includes `funcName:lineno`. Debug-level logs include raw user answer dicts.

## Slash command sync

`tree.sync()` runs on every `on_ready` and is **global** (no `guild=` arg). Global syncs are rate-limited and can take up to an hour to propagate. For dev work, register to a specific guild instead.

## Deployment notes

- `Dockerfile` runs as non-root `appuser` (uid 1000) and sets `MALLOC_ARENA_MAX=2` to reduce glibc fragmentation
- `railway.json` configures `ON_FAILURE` restart with up to 10 retries — combined with in-memory quiz state, this means a flaky deploy can silently wipe active quizzes multiple times
- `h11==0.16.0` is pinned in `requirements.txt` for a security fix; if you bump `discord.py` or `openai`, verify `h11` compatibility
