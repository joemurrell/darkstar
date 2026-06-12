"""
DarkstarAIC - DCS Air Control Communication Discord Bot
PDF-grounded Q&A and Quiz system using the Anthropic Claude API
(ACC text embedded as a cached system prompt + tool-use structured output).
"""
import os
import asyncio
import json
import random
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Set, Tuple, Union
from collections import Counter
from difflib import SequenceMatcher
import re
import discord
from discord import app_commands
from anthropic import AsyncAnthropic, APITimeoutError, RateLimitError

import db

# Environment variables
DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
# Claude model to use. Defaults to Haiku 4.5 for cost; bump to
# claude-sonnet-4-6 for higher-quality quiz generation.
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5")
# Path to the extracted ACC document text. Generate with
# scripts/extract_pdf.py and commit the result. Sent as cached plain text
# (not a Files-API document block) to avoid the per-page image tokens that
# pushed a single request past the Tier 1 50K-input-token-per-minute limit.
ACC_DOCUMENT_PATH = os.environ.get("ACC_DOCUMENT_PATH", "acc_document.txt")
# SQLite file for quiz persistence. On Railway, point this at a mounted
# volume (e.g. /data/darkstar.db) so in-flight quizzes survive deploys.
DARKSTAR_DB_PATH = os.environ.get("DARKSTAR_DB_PATH", "darkstar.db")
# Pre-generated question bank (a JSON list of question dicts). /quiz_start
# samples this pool instead of calling Claude, so quizzes are instant and free.
# Generate it once with scripts/generate_quiz_bank.py and commit the result;
# the bot falls back to live generation whenever the bank can't satisfy a
# request (before it's seeded, or for a narrow topic filter).
ACC_QUESTIONS_PATH = os.environ.get("ACC_QUESTIONS_PATH", "acc_questions.json")
# Per-user rate limit on /ask: at most ASK_RATE_LIMIT calls per user within any
# ASK_RATE_WINDOW_SECONDS sliding window (tracked per user, across channels).
# Set ASK_RATE_LIMIT=0 to disable the limit.
ASK_RATE_LIMIT = int(os.environ.get("ASK_RATE_LIMIT", "5"))
ASK_RATE_WINDOW_SECONDS = int(os.environ.get("ASK_RATE_WINDOW_SECONDS", "3600"))

# --- Discord client setup ---
intents = discord.Intents.default()
# max_messages=None disables discord.py's default 1000-message cache. The bot
# never reads cached messages (quiz state lives in QUIZ_STATE/SQLite and buttons
# route by custom_id), so the cache is pure idle memory overhead.
client = discord.Client(intents=intents, max_messages=None)
tree = app_commands.CommandTree(client)

# --- Anthropic client ---
anthropic_client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

# Configure logging for Railway compatibility
# Railway prefers structured JSON logs with clear levels
# Reference: https://docs.railway.com/guides/logs
import sys

# Configure logging - stdout only (Railway captures stdout)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(funcName)s:%(lineno)d | %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

# Create logger instances for different components
logger = logging.getLogger(__name__)
discord_logger = logging.getLogger('discord_bot')
quiz_logger = logging.getLogger('quiz')
api_logger = logging.getLogger('anthropic_api')

# In-memory quiz state (per-channel). The source of truth for the hot path
# (button clicks, timers); the QuizStore below mirrors it to SQLite so it
# survives restarts.
QUIZ_STATE = {}

# Quiz persistence store, opened once in on_ready. Persistence is best-effort:
# every DB call is wrapped so a storage failure degrades to in-memory-only
# behavior rather than breaking a live quiz. None until startup completes.
quiz_store: "db.QuizStore | None" = None
_startup_done = False

# Per-user /ask timestamps for rate limiting: {user_id: [datetime, ...]}, kept
# pruned to the active window on each check. Grows only with distinct users.
ASK_HISTORY: dict = {}

# System prompt — defines DarkstarAIC's persona and grounding rules. Edit
# directly to tune tone or refusal behavior; the value is cached prefix so
# changes invalidate the prompt cache until the new prefix is re-warmed.
ACC_INSTRUCTIONS = """You are DarkstarAIC, an AI assistant for a DCS (Digital Combat Simulator World) flight squadron. You help squadron members learn and practice the concepts, terminology, and application of the Air Control Communication (ACC) multi-Service tactics, techniques, and procedures (MTTP) publication — more commonly known as air intercept control, C2, or AWACS.

Grounding rules:
- Answer only from the ACC documentation provided below. If the answer is not in it, say exactly: "That information is not available in the ACC documentation."
- Cite page numbers inline (e.g. "see p. 42") whenever you reference a procedure.
- Use proper military aviation terminology. Be concise but thorough, and don't soften technical detail.

When generating quizzes:
- Build realistic scenarios with proper context that test the knowledge controllers and pilots actually need.
- Make every question cover a distinct concept — don't repeat the same terminology across questions.
- Write distractors that are plausible to a novice but unambiguously wrong to someone who knows the material.
- Always explain the correct answer and include its page reference."""

# The extracted ACC document text, loaded once at startup. Tolerant of a
# missing file so the module imports cleanly in tests; on_ready validates it
# is non-empty and logs loudly if not.
try:
    with open(ACC_DOCUMENT_PATH, encoding="utf-8") as _fh:
        ACC_DOCUMENT_TEXT = _fh.read()
except FileNotFoundError:
    ACC_DOCUMENT_TEXT = ""

# The cached system prefix, built once at startup. ask_assistant reuses this
# same list on every request rather than rebuilding the f"ACC documentation:..."
# string (a ~180KB copy of the whole document) per call. The SDK serializes but
# never mutates it, and the contents are static, so sharing is safe.
ACC_SYSTEM_BLOCKS = [
    {"type": "text", "text": ACC_INSTRUCTIONS},
    {
        "type": "text",
        "text": f"ACC documentation:\n\n{ACC_DOCUMENT_TEXT}",
        "cache_control": {"type": "ephemeral"},
    },
]


# --- Button Classes for Quiz Interaction ---

# Answer buttons are persistent *dynamic* items: all of their state lives in the
# custom_id, so after a restart `client.add_dynamic_items(QuizAnswerButton)`
# (in on_ready) re-attaches a handler to buttons posted before the restart —
# no need to persist message IDs or re-send the questions. The channel id in
# the custom_id also keeps it globally unique across concurrent quizzes in
# different channels (discord.py routes persistent components by custom_id).
QUIZ_BUTTON_TEMPLATE = r"quiz:(?P<channel>\d+):(?P<q>\d+):(?P<choice>[ABCD])"


def quiz_button_custom_id(channel_id: int, question_idx: int, choice: str) -> str:
    """The stable custom_id for one answer button (channel + question + choice)."""
    return f"quiz:{channel_id}:{question_idx}:{choice}"


class QuizAnswerButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=QUIZ_BUTTON_TEMPLATE,
):
    """A persistent answer button; its channel/question/choice live in the custom_id."""

    def __init__(self, channel_id: int, question_idx: int, choice: str):
        super().__init__(
            discord.ui.Button(
                style=discord.ButtonStyle.primary,
                label=f"{choice}",
                custom_id=quiz_button_custom_id(channel_id, question_idx, choice),
            )
        )
        self.channel_id = channel_id
        self.question_idx = question_idx
        self.choice = choice

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item, match):
        """Rebuild the button from a matched custom_id (used for clicks after a restart)."""
        return cls(int(match["channel"]), int(match["q"]), match["choice"])

    async def callback(self, interaction: discord.Interaction):
        """Handle button click."""
        quiz_logger.info(f"Button click: user={interaction.user.name}({interaction.user.id}) guild={interaction.guild.name if interaction.guild else 'DM'}({interaction.guild_id if interaction.guild else 'N/A'}) channel={interaction.channel_id} question={self.question_idx+1} choice={self.choice}")
        
        state = QUIZ_STATE.get(interaction.channel_id)
        if not state:
            quiz_logger.warning(f"No quiz running in channel {interaction.channel_id} for user {interaction.user.name}({interaction.user.id})")
            await interaction.response.send_message(
                "❌ No quiz is running in this channel.",
                ephemeral=True
            )
            return
        
        # Check if quiz has ended
        if datetime.now(timezone.utc) >= state["end_time"]:
            quiz_logger.warning(f"User {interaction.user.name}({interaction.user.id}) attempted to answer after quiz ended in channel {interaction.channel_id}")
            await interaction.response.send_message(
                "❌ This quiz has ended! Results are being calculated.",
                ephemeral=True
            )
            return
        
        # Validate question number
        if self.question_idx < 0 or self.question_idx >= len(state["questions"]):
            quiz_logger.error(f"Invalid question index {self.question_idx} for user {interaction.user.name}({interaction.user.id}) in channel {interaction.channel_id}")
            await interaction.response.send_message(
                "❌ Invalid question.",
                ephemeral=True
            )
            return
        
        user_id = str(interaction.user.id)
        
        # Initialize user's answers if needed
        if user_id not in state["user_answers"]:
            state["user_answers"][user_id] = {}
            quiz_logger.debug(f"Initialized answer dict for user {interaction.user.name}({user_id}) in channel {interaction.channel_id}")
        
        # Store the answer (memory is the hot-path source of truth; mirror to DB)
        state["user_answers"][user_id][self.question_idx] = self.choice
        await _persist_answer(state, self.question_idx, interaction.user.id, self.choice)
        quiz_logger.info(f"Stored answer: user={interaction.user.name}({user_id}) channel={interaction.channel_id} q={self.question_idx+1} answer={self.choice}")

        # Calculate how many questions they've answered
        answered_count = len(state["user_answers"][user_id])
        total_questions = len(state["questions"])
        
        minutes_remaining, seconds_remaining = format_time_remaining(state["end_time"])

        quiz_logger.debug(f"User {interaction.user.name}({user_id}) progress: {answered_count}/{total_questions} answered, {minutes_remaining}m {seconds_remaining}s remaining")

        await interaction.response.send_message(
            f"📝 Answer **{self.choice}** recorded for question {self.question_idx + 1}!\n"
            f"📊 You've answered {answered_count}/{total_questions} questions.\n"
            f"⏱️ Time remaining: {minutes_remaining}m {seconds_remaining}s",
            ephemeral=True
        )


def build_question_view(channel_id: int, question_idx: int, options: List[str]) -> discord.ui.View:
    """
    Build a persistent view of answer buttons (A..D) for one question. timeout
    is None because the quiz runs its own timer; routing for clicks survives a
    restart via the registered QuizAnswerButton dynamic item, not this object.
    """
    view = discord.ui.View(timeout=None)
    choices = ["A", "B", "C", "D"]
    for choice in choices[:len(options)]:
        view.add_item(QuizAnswerButton(channel_id, question_idx, choice))
    return view


# --- Helper Functions ---

async def check_bot_permissions(interaction: discord.Interaction) -> Tuple[bool, Optional[str]]:
    """
    Check if the bot has required permissions in the current channel.
    Returns (has_permissions, error_message).
    
    Required permissions:
    - Send Messages
    - Embed Links
    - Read Message History
    - View Channel
    """
    if not interaction.guild:
        # DM channels - bot always has permissions
        return True, None
    
    channel = interaction.channel
    bot_member = interaction.guild.get_member(client.user.id)
    
    if not bot_member:
        return False, "❌ Bot member not found in guild."
    
    # Get bot's effective permissions in the channel
    bot_perms = channel.permissions_for(bot_member)
    
    # Define required permissions. `use_application_commands` is what gates
    # slash commands from appearing in the first place, so missing it is a
    # very common cause of "the bot doesn't see my command".
    required_perms = {
        "send_messages": "Send Messages",
        "embed_links": "Embed Links",
        "read_message_history": "Read Message History",
        "view_channel": "View Channel",
        "use_application_commands": "Use Application Commands",
    }
    
    # Check which permissions are missing
    missing_perms = []
    for perm_attr, perm_name in required_perms.items():
        if not getattr(bot_perms, perm_attr, False):
            missing_perms.append(perm_name)
    
    if not missing_perms:
        return True, None
    
    # Permissions are missing - identify the cause
    error_parts = ["❌ **Missing Permissions in this channel:**"]
    error_parts.append(f"Missing: {', '.join(f'**{p}**' for p in missing_perms)}")
    error_parts.append("")
    error_parts.append("**Cause Analysis:**")
    
    # Check channel overwrites to find blockers
    blockers = []
    
    # Check @everyone overwrite
    everyone_overwrite = channel.overwrites_for(interaction.guild.default_role)
    for perm_attr, perm_name in required_perms.items():
        perm_value = getattr(everyone_overwrite, perm_attr, None)
        if perm_value is False:  # Explicitly denied
            blockers.append(f"• @everyone role explicitly **denies** `{perm_name}`")
    
    # Check bot's role overwrites
    for role in bot_member.roles:
        if role == interaction.guild.default_role:
            continue
        role_overwrite = channel.overwrites_for(role)
        for perm_attr, perm_name in required_perms.items():
            perm_value = getattr(role_overwrite, perm_attr, None)
            if perm_value is False:  # Explicitly denied
                blockers.append(f"• Role {role.mention} explicitly **denies** `{perm_name}`")
    
    # Check member-specific overwrite (rare but possible)
    member_overwrite = channel.overwrites_for(bot_member)
    for perm_attr, perm_name in required_perms.items():
        perm_value = getattr(member_overwrite, perm_attr, None)
        if perm_value is False:  # Explicitly denied
            blockers.append(f"• Bot member override explicitly **denies** `{perm_name}`")
    
    if blockers:
        error_parts.extend(blockers)
    else:
        # No explicit denies found - must be missing from base roles
        error_parts.append("• The bot's roles don't grant these permissions globally")
        error_parts.append("• No channel overwrites are blocking (but none are allowing either)")
    
    error_parts.append("")
    error_parts.append("**How to fix:**")
    error_parts.append("1. Check channel permission overwrites for roles/members")
    error_parts.append("2. Grant the bot's role the required permissions server-wide, OR")
    error_parts.append("3. Add channel-specific permission overwrites to allow the bot")

    message = "\n".join(error_parts)
    # Discord interaction messages cap at 2000 chars. With many roles/blockers
    # this diagnostic can blow past that and the whole send fails silently.
    if len(message) > 1900:
        message = message[:1897] + "..."
    return False, message

def model_supports_temperature(model: Optional[str]) -> bool:
    """
    Claude Opus 4.7 removed the `temperature` parameter and returns 400 if it
    is sent. All earlier Claude models (Sonnet 4.6, Haiku 4.5, Opus 4.6 and
    older) accept it. Defaults to True for unknown / non-Claude models.
    """
    if not model:
        return True
    return not model.startswith("claude-opus-4-7")


def rate_limit_ask(user_id: int, now: Optional[datetime] = None) -> Optional[int]:
    """
    Enforce the per-user sliding-window rate limit on /ask. Prunes the user's
    history to the active window and, when the request is allowed, records this
    attempt and returns None. When the user is at the limit, returns the integer
    seconds until their oldest in-window request expires (a slot frees up).
    ASK_RATE_LIMIT <= 0 disables the limit (always returns None).
    """
    if ASK_RATE_LIMIT <= 0:
        return None
    now = now or datetime.now(timezone.utc)
    window_start = now - timedelta(seconds=ASK_RATE_WINDOW_SECONDS)
    # History is appended in time order and only ever filtered, so it stays
    # sorted ascending — history[0] is the oldest still-counting request.
    history = [t for t in ASK_HISTORY.get(user_id, []) if t > window_start]
    if len(history) >= ASK_RATE_LIMIT:
        ASK_HISTORY[user_id] = history
        retry_after = (history[0] + timedelta(seconds=ASK_RATE_WINDOW_SECONDS)) - now
        return max(1, int(retry_after.total_seconds()) + 1)
    history.append(now)
    ASK_HISTORY[user_id] = history
    # Opportunistically drop other users whose entire history has aged out of
    # the window. Without this, ASK_HISTORY keeps one (eventually empty) list
    # per distinct user ever seen and grows unbounded while the bot is idle;
    # pruning here bounds it to users active within the window. /ask is itself
    # rate-limited so this sweep over a small dict runs rarely and cheaply.
    stale = [
        uid for uid, ts in ASK_HISTORY.items()
        if not ts or ts[-1] <= window_start
    ]
    for uid in stale:
        del ASK_HISTORY[uid]
    return None


async def ask_assistant(
    user_msg: str,
    timeout: int = 30,
    temperature: Optional[float] = None,
    tool: Optional[dict] = None,
) -> Union[str, dict, None]:
    """
    Ask Claude a question grounded in the ACC documentation (embedded as
    cached plain text in the system prompt).

    The instructions + document text form the cached prefix (`cache_control:
    ephemeral` on the document block), so the ~45K-token prefix is served from
    cache on every request after the first one in a 5-minute window. Cache
    reads don't count toward the ITPM rate limit on Haiku 4.5, so only the
    first cold write spends meaningfully against it.

    Args:
        user_msg: The user question / quiz prompt.
        timeout: Maximum seconds before the SDK raises APITimeoutError.
        temperature: Optional temperature (Claude accepts 0.0-1.0). Skipped
            on models that reject it (Opus 4.7).
        tool: Optional tool spec dict (`name`, `description`, `input_schema`).
            When provided, Claude is forced to call exactly this tool and the
            tool's input dict is returned directly — no JSON parsing needed.
            Returns None if Claude refuses or no tool_use block is emitted.

    Returns:
        - str: plain-text response when `tool` is None.
        - dict: parsed tool input when `tool` is provided.
        - None: when forced tool-use was requested but the model refused.
    """
    api_logger.debug(
        f"ask_assistant called: msg_len={len(user_msg)} timeout={timeout} "
        f"temperature={temperature} tool={tool['name'] if tool else None}"
    )

    request_params = {
        "model": CLAUDE_MODEL,
        "max_tokens": 4096,
        # Instructions + the full ACC document text form the cached prefix.
        # The cache_control breakpoint sits on the document block (the last,
        # largest, static block), so the whole prefix is written once and
        # served from cache thereafter. The varying user question lands in
        # `messages`, after the breakpoint, so it never invalidates the cache.
        # Built once at module load (ACC_SYSTEM_BLOCKS) to avoid re-allocating
        # the ~180KB document string on every request.
        "system": ACC_SYSTEM_BLOCKS,
        "messages": [{"role": "user", "content": user_msg}],
    }

    if temperature is not None and model_supports_temperature(CLAUDE_MODEL):
        request_params["temperature"] = temperature

    if tool is not None:
        request_params["tools"] = [tool]
        request_params["tool_choice"] = {"type": "tool", "name": tool["name"]}
        # Give forced tool-use plenty of room — quiz schemas with N questions
        # generate a few KB of structured output.
        request_params["max_tokens"] = 8000

    try:
        response = await anthropic_client.messages.create(
            **request_params, timeout=timeout
        )

        usage = response.usage
        api_logger.info(
            f"Response received: id={response.id} stop_reason={response.stop_reason} "
            f"input={usage.input_tokens} cache_read={usage.cache_read_input_tokens} "
            f"cache_write={usage.cache_creation_input_tokens} output={usage.output_tokens}"
        )

        if response.stop_reason == "refusal":
            api_logger.warning("Claude refused the request")
            return None if tool is not None else "❌ The AI declined to answer this question."

        # Forced tool-use path: return the parsed tool input dict.
        if tool is not None:
            for block in response.content:
                if block.type == "tool_use" and block.name == tool["name"]:
                    return block.input
            # No tool_use block found — log enough to diagnose (stop_reason
            # max_tokens means the tool call was cut off; an unexpected block
            # set points at a server-side issue).
            api_logger.warning(
                f"Forced tool {tool['name']} but no tool_use block: "
                f"stop_reason={response.stop_reason} "
                f"blocks={[b.type for b in response.content]}"
            )
            return None

        # Plain-text path: concatenate text blocks.
        chunks = [block.text for block in response.content if block.type == "text"]
        if not chunks:
            api_logger.warning("No text content found in response")
            return "No response from assistant."

        result = "\n".join(chunks)
        api_logger.info(f"Assistant response received: length={len(result)}")
        return result

    except RateLimitError as e:
        # 429. On Tier 1 the ACC PDF's first (cold-cache) request can exceed
        # the per-minute input-token limit on its own. Surface a clear, honest
        # message with the retry window instead of the generic error.
        retry_after = "60"
        if getattr(e, "response", None) is not None:
            retry_after = e.response.headers.get("retry-after", "60")
        api_logger.error(f"Rate limited (429): retry-after={retry_after}s — {e}")
        msg = (
            f"❌ Hit the API rate limit — the ACC document is large for the "
            f"current usage tier. Wait ~{retry_after}s and try again."
        )
        return None if tool is not None else msg
    except APITimeoutError:
        api_logger.error(f"Anthropic request timed out after {timeout}s")
        msg = "❌ The AI took too long to respond. Please try again in a moment."
        return None if tool is not None else msg
    except Exception as e:
        # Log the exception type explicitly — BadRequestError vs OverloadedError
        # point at very different root causes.
        api_logger.error(f"Error asking assistant ({type(e).__name__}): {e}", exc_info=True)
        return None if tool is not None else f"❌ Error communicating with AI: {str(e)}"


def format_time_remaining(end_time: datetime) -> Tuple[int, int]:
    """
    Return (minutes, seconds) of time remaining until end_time, bounded at 0
    so callers don't display negative durations during the race between an
    end-time check and a display update.
    """
    delta = end_time - datetime.now(timezone.utc)
    total = max(0, int(delta.total_seconds()))
    return total // 60, total % 60


def truncate_for_discord(text: str, limit: int = 2000) -> str:
    """
    Truncate text to fit Discord's per-message char limit, closing any open
    triple-backtick fence so markdown rendering doesn't break.
    """
    if len(text) <= limit:
        return text
    # Reserve room for the ellipsis and a possible closing fence on its own line.
    head = text[: limit - 8]
    if head.count("```") % 2 == 1:
        head = head.rstrip() + "\n```"
    return head + "..."


def chunk_mentions(user_ids: List[str], base_name: str, max_chars: int = 1024) -> List[Tuple[str, str]]:
    """
    Pack a list of user IDs into Discord embed fields under the 1024-char value
    limit. Returns a list of (field_name, field_value) tuples; pages are
    suffixed when more than one field is needed.
    """
    if not user_ids:
        return []
    pages: List[str] = []
    current: List[str] = []
    current_len = 0
    for uid in user_ids:
        mention = f"<@{uid}>"
        addition = len(mention) + (2 if current else 0)  # ", " separator
        if current and current_len + addition > max_chars:
            pages.append(", ".join(current))
            current = [mention]
            current_len = len(mention)
        else:
            current.append(mention)
            current_len += addition
    if current:
        pages.append(", ".join(current))
    if len(pages) == 1:
        return [(base_name, pages[0])]
    return [(f"{base_name} ({i+1}/{len(pages)})", page) for i, page in enumerate(pages)]


def format_mcq(question: str, options: List[str], question_num: int = None, total: int = None) -> discord.Embed:
    """Format a multiple choice question as a Discord embed with forest green border."""
    letters = ["A", "B", "C", "D", "E", "F"][:len(options)]
    
    # Clean options to remove any leading letter prefixes
    cleaned_options = []
    for opt in options:
        # Strip leading whitespace
        cleaned = opt.strip()
        # Remove leading letter prefix patterns: "A)", "A.", "A:", "A -", etc.
        if len(cleaned) >= 2 and cleaned[0].upper() in 'ABCDEF':
            second_char = cleaned[1]
            # Check for common separators after the letter
            if second_char in ').:- ':
                # Find where the actual text starts (skip past separator and whitespace)
                start_idx = 2
                while start_idx < len(cleaned) and cleaned[start_idx] in ' \t':
                    start_idx += 1
                cleaned = cleaned[start_idx:]
        cleaned_options.append(cleaned)
    
    # Forest green color similar to flight suit (hex #2d5016)
    embed = discord.Embed(
        color=0x2d5016
    )
    
    # Add question number as non-bold text if provided
    if question_num is not None and total is not None:
        embed.description = f"Question {question_num}/{total}\n\n**{question}**"
    else:
        embed.description = f"**{question}**"
    
    # Add options as a field
    options_text = "\n".join(f"**{letter})** {opt}" for letter, opt in zip(letters, cleaned_options))
    embed.add_field(name="\u200b", value=options_text, inline=False)
    
    return embed


def shuffle_quiz_options(question: dict) -> dict:
    """
    Shuffle the options in a quiz question and update the correct answer letter.
    Returns a new dict with shuffled options + updated answer; preserves every
    other field from the original (topic, page, and anything else the LLM
    emits).
    """
    # Get the original correct answer index (A=0, B=1, C=2, D=3)
    answer_letter = question["answer"].strip().upper()
    answer_index = ord(answer_letter) - ord('A')

    options_with_correctness = [
        (opt, i == answer_index)
        for i, opt in enumerate(question["options"])
    ]
    random.shuffle(options_with_correctness)

    new_answer_index = next(
        i for i, (_, is_correct) in enumerate(options_with_correctness)
        if is_correct
    )

    shuffled_question = dict(question)
    shuffled_question["options"] = [opt for opt, _ in options_with_correctness]
    shuffled_question["answer"] = chr(ord('A') + new_answer_index)
    return shuffled_question


# --- Deduplication Helper Functions ---

STOPWORDS = {
    'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
    'of', 'with', 'by', 'from', 'is', 'are', 'was', 'were', 'be', 'been',
    'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
    'should', 'could', 'may', 'might', 'must', 'can', 'what', 'which',
    'who', 'when', 'where', 'why', 'how', 'this', 'that', 'these', 'those'
}


def extract_topic_from_question(question_dict: dict) -> str:
    """
    Extract or compute a topic tag for a question.
    Uses the 'topic' field if present, otherwise extracts from question text.
    
    Args:
        question_dict: Question dictionary with 'q' and optionally 'topic' fields
    
    Returns:
        A normalized topic string (lowercase, hyphenated)
    """
    # Use provided topic if available
    if "topic" in question_dict and question_dict["topic"]:
        return question_dict["topic"].lower().strip()
    
    # Extract from question text
    question_text = question_dict.get("q", "").lower()
    
    # Remove punctuation and split into words
    words = re.findall(r'\b[a-z]+\b', question_text)
    
    # Filter out stopwords and short words
    content_words = [w for w in words if w not in STOPWORDS and len(w) > 3]
    
    # Count word frequencies
    if not content_words:
        return "unknown"
    
    word_counts = Counter(content_words)
    
    # Take top 2-3 most common words
    top_words = [word for word, _ in word_counts.most_common(3)]
    
    # Create hyphenated topic tag
    topic = "-".join(top_words[:2]) if len(top_words) >= 2 else (top_words[0] if top_words else "unknown")
    
    return topic


def extract_keywords(text: str, top_n: int = 5) -> Set[str]:
    """
    Extract top N keywords from text (after removing stopwords).
    
    Args:
        text: Input text
        top_n: Number of top keywords to extract
    
    Returns:
        Set of top keywords
    """
    text = text.lower()
    words = re.findall(r'\b[a-z]+\b', text)
    content_words = [w for w in words if w not in STOPWORDS and len(w) > 3]
    
    if not content_words:
        return set()
    
    word_counts = Counter(content_words)
    return set(word for word, _ in word_counts.most_common(top_n))


def are_questions_similar(q1: dict, q2: dict, topic1: str, topic2: str) -> bool:
    """
    Determine if two questions are too similar and should be considered duplicates.
    
    Considers questions duplicates if:
    - Topics match exactly
    - Question text similarity > 85% (fuzzy ratio)
    - Share > 40% of top 5 keywords
    
    Args:
        q1, q2: Question dictionaries
        topic1, topic2: Topic tags for the questions
    
    Returns:
        True if questions are too similar
    """
    # Check exact topic match
    if topic1 == topic2:
        return True
    
    # Check fuzzy text similarity
    text1 = q1.get("q", "")
    text2 = q2.get("q", "")
    
    if SequenceMatcher(None, text1.lower(), text2.lower()).ratio() * 100 > 85:
        return True
    
    # Check keyword overlap
    keywords1 = extract_keywords(text1)
    keywords2 = extract_keywords(text2)
    
    if keywords1 and keywords2:
        overlap = len(keywords1 & keywords2)
        total = len(keywords1 | keywords2)
        if total > 0 and overlap / total > 0.4:
            return True
    
    return False


def deduplicate_questions(questions: List[dict]) -> Tuple[List[dict], List[str]]:
    """
    Remove duplicate/similar questions from a list.
    
    Args:
        questions: List of question dictionaries
    
    Returns:
        Tuple of (unique_questions, used_topics)
    """
    unique = []
    topics = []
    
    for q in questions:
        topic = extract_topic_from_question(q)
        
        # Check if this question is similar to any already in unique list
        is_duplicate = False
        for existing_q, existing_topic in zip(unique, topics):
            if are_questions_similar(q, existing_q, topic, existing_topic):
                is_duplicate = True
                break
        
        if not is_duplicate:
            unique.append(q)
            topics.append(topic)
    
    return unique, topics


# OpenAI Responses-API structured-output spec for quiz generation. The model
# is forced to return an object with a `questions` array whose items have all
# required fields (including `topic`, which the dedup logic depends on).
# Forced tool spec for quiz generation. Claude is required to call this tool
# (via tool_choice), and the parsed dict comes back directly on the tool_use
# block — no JSON-string parsing, no fence-stripping, no validation against
# free-form text. The tool's input_schema is the structured-output spec.
QUIZ_TOOL = {
    "name": "submit_quiz",
    "description": (
        "Submit a set of multiple-choice quiz questions about the ACC "
        "documentation. Every question must have exactly 4 options, a correct "
        "answer letter, an explanation with a page reference, the page "
        "number as an integer, and a short hyphenated topic tag."
    ),
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "questions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "q": {"type": "string"},
                        "options": {"type": "array", "items": {"type": "string"}},
                        "answer": {"type": "string", "enum": ["A", "B", "C", "D"]},
                        "explain": {"type": "string"},
                        "page": {"type": "integer"},
                        "topic": {"type": "string"},
                    },
                    "required": ["q", "options", "answer", "explain", "page", "topic"],
                },
            }
        },
        "required": ["questions"],
    },
}


def validate_quiz_questions(items: List[dict]) -> List[dict]:
    """
    Filter to questions with the required shape; normalize the answer letter.
    Returns shallow-copied dicts so the caller's data isn't mutated. Skips
    any non-dict items defensively — the tool input_schema enforces shape on
    Claude's side but the validator is the second line of defense.
    """
    valid = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        if not all(k in raw for k in ("q", "options", "answer", "explain")):
            continue
        if not isinstance(raw["options"], list) or len(raw["options"]) != 4:
            continue
        item = dict(raw)
        item["answer"] = str(item["answer"]).strip().upper()
        if item["answer"] not in ("A", "B", "C", "D"):
            continue
        valid.append(item)
    return valid


def load_question_bank(path: str = ACC_QUESTIONS_PATH) -> List[dict]:
    """
    Load the pre-generated question bank (a JSON list of question dicts) and
    validate each entry against the quiz schema. Returns [] if the file is
    missing, isn't valid JSON, or isn't a list — the bot then falls back to
    live generation in /quiz_start.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return validate_quiz_questions(data)


def sample_questions(bank: List[dict], num_questions: int, topic: str = "") -> List[dict]:
    """
    Sample up to `num_questions` questions from the bank, spread across distinct
    topic tags (round-robin over shuffled topics) so a single quiz doesn't draw
    several near-identical questions from one topic. Sampling is random and
    without replacement within a quiz; repeats *across* separate quizzes are
    expected and fine given a reasonably sized pool.

    When `topic` is given, only questions whose topic tag or text contains it
    (case-insensitive) are eligible, and [] is returned if none match so the
    caller can fall back to live generation for that topic.
    """
    if not bank or num_questions <= 0:
        return []
    candidates = bank
    if topic:
        needle = topic.lower().strip()
        candidates = [
            q for q in bank
            if needle in (q.get("topic") or "").lower() or needle in q.get("q", "").lower()
        ]
        if not candidates:
            return []
    # Bucket by topic tag, shuffle within and across buckets, then round-robin
    # so the selection spreads over as many distinct topics as possible.
    groups: dict = {}
    for q in candidates:
        key = (q.get("topic") or extract_topic_from_question(q)).lower()
        groups.setdefault(key, []).append(q)
    for items in groups.values():
        random.shuffle(items)
    topic_keys = list(groups.keys())
    random.shuffle(topic_keys)
    selected: List[dict] = []
    i = 0
    while len(selected) < num_questions and any(groups[k] for k in topic_keys):
        bucket = groups[topic_keys[i % len(topic_keys)]]
        if bucket:
            selected.append(bucket.pop())
        i += 1
    return selected


# The question bank, loaded once at import. Empty until seeded with
# scripts/generate_quiz_bank.py; on_ready logs the size and /quiz_start falls
# back to live generation while it's empty.
QUESTION_BANK: List[dict] = load_question_bank()


async def _request_quiz_questions(prompt: str, temperature: float) -> List[dict]:
    """Single quiz-generation API call. Returns validated questions or []."""
    # 90s timeout: the first quiz call after a cold cache must process the full
    # ~50K-token PDF (cache write) before generating, which can outlast the
    # 30s default on a slow first hit.
    result = await ask_assistant(
        prompt, timeout=90, temperature=temperature, tool=QUIZ_TOOL,
    )
    if not isinstance(result, dict) or "questions" not in result:
        api_logger.warning(f"submit_quiz returned no questions: {type(result).__name__}")
        return []
    return validate_quiz_questions(result["questions"])


async def generate_quiz(topic_hint: str = "", num_questions: int = 6) -> Optional[List[dict]]:
    """
    Generate a quiz from the PDF using Claude.
    Forces tool-use against QUIZ_TOOL so the response is a validated dict,
    then deduplicates and regenerates for diversity. Returns a list of
    question dicts or None on failure.
    """
    max_regeneration_attempts = 3

    prompt = (
        f"Generate {num_questions} multiple-choice questions based ONLY on the ACC documentation.\n\n"
        "Requirements:\n"
        "- Each question must have exactly 4 options\n"
        "- Provide a brief explanation with a page reference like (p.XX) in `explain`\n"
        "- Set `page` to the integer page number from the PDF\n"
        "- Set `topic` to a short hyphenated tag identifying the concept (e.g. \"fuel-system\", \"emergency-procedures\")\n"
        "- Focus on practical knowledge for DCS pilots\n"
        "- Every question must cover a different topic from the others; do not repeat distinctive keywords\n\n"
        + (f"Topic focus: {topic_hint}" if topic_hint else "Cover various topics from the document.")
        + "\n\nCall the submit_quiz tool with your questions."
    )

    api_logger.info(f"Generating quiz: topic_hint='{topic_hint}', num_questions={num_questions}")

    try:
        valid_questions = await _request_quiz_questions(prompt, temperature=0.7)

        if not valid_questions:
            api_logger.warning("No valid questions returned from assistant")
            return None

        unique_questions, used_topics = deduplicate_questions(valid_questions)
        api_logger.info(
            f"After deduplication: {len(unique_questions)} unique out of "
            f"{len(valid_questions)} initial questions"
        )
        api_logger.info(f"Used topics: {used_topics}")

        # Regeneration loop if we don't have enough unique questions.
        attempt = 0
        while len(unique_questions) < num_questions and attempt < max_regeneration_attempts:
            attempt += 1
            needed = num_questions - len(unique_questions)
            api_logger.info(
                f"Regeneration attempt {attempt}/{max_regeneration_attempts}: "
                f"need {needed} more questions"
            )

            regen_prompt = (
                f"Generate {needed + 2} additional multiple-choice questions based ONLY on the ACC documentation.\n\n"
                f"Do NOT repeat any of these topics (already covered): {', '.join(used_topics)}\n\n"
                "Same requirements as before: 4 options, A/B/C/D answer letter, explanation with page reference, integer page, hyphenated topic tag.\n"
                "Each new question must have a unique topic tag different from the ones listed above.\n\n"
                + (f"Topic focus: {topic_hint}" if topic_hint else "Cover various unused topics from the document.")
                + "\n\nCall the submit_quiz tool with your questions."
            )

            regen_valid = await _request_quiz_questions(regen_prompt, temperature=0.8)

            for q in regen_valid:
                topic = extract_topic_from_question(q)
                is_duplicate = any(
                    are_questions_similar(q, existing_q, topic, existing_topic)
                    for existing_q, existing_topic in zip(unique_questions, used_topics)
                )
                if not is_duplicate:
                    unique_questions.append(q)
                    used_topics.append(topic)
                    api_logger.debug(f"Added new unique question with topic: {topic}")
                    if len(unique_questions) >= num_questions:
                        break

        final_count = len(unique_questions)
        api_logger.info(f"Final quiz: {final_count} unique questions (requested: {num_questions})")
        api_logger.info(f"Final topics: {used_topics}")

        if final_count >= num_questions:
            result = unique_questions[:num_questions]
            api_logger.info(f"Returning {len(result)} questions")
            return result
        elif final_count > 0:
            api_logger.warning(
                f"Could only generate {final_count} unique questions "
                f"(requested {num_questions})"
            )
            return unique_questions
        else:
            api_logger.error("Failed to generate any unique questions")
            return None

    except Exception as e:
        api_logger.error(f"Quiz generation error: {e}", exc_info=True)
        return None


async def _persist_answer(state: dict, position: int, user_id: int, choice: str) -> None:
    """Best-effort mirror of an answer to SQLite. Never breaks the live quiz."""
    quiz_id = state.get("quiz_id")
    if quiz_store is None or quiz_id is None:
        return
    try:
        await quiz_store.record_answer(
            quiz_id=quiz_id,
            position=position,
            user_id=user_id,
            choice=choice,
            answered_at=datetime.now(timezone.utc),
        )
    except Exception as e:
        quiz_logger.error(f"Failed to persist answer (quiz_id={quiz_id}): {e}", exc_info=True)


async def _persist_completion(state: dict) -> None:
    """Best-effort mark-quiz-completed in SQLite."""
    quiz_id = state.get("quiz_id")
    if quiz_store is None or quiz_id is None:
        return
    try:
        await quiz_store.complete_quiz(quiz_id)
    except Exception as e:
        quiz_logger.error(f"Failed to mark quiz completed (quiz_id={quiz_id}): {e}", exc_info=True)


async def auto_end_quiz(channel_id: int, channel):
    """
    End the quiz when its stored end_time arrives. Sleeps the remaining time
    derived from state["end_time"] (rather than a fixed duration) so a quiz
    rehydrated after a restart resumes with the correct remaining window.
    """
    state = QUIZ_STATE.get(channel_id)
    if not state:
        return
    remaining = (state["end_time"] - datetime.now(timezone.utc)).total_seconds()
    quiz_logger.info(f"Auto-end task started for channel {channel_id}, ending in {remaining:.0f}s")

    try:
        if remaining > 0:
            await asyncio.sleep(remaining)

        # Check if quiz still exists (manual /quiz_end may have ended it)
        if not QUIZ_STATE.get(channel_id):
            quiz_logger.warning(f"Auto-end: quiz no longer exists in channel {channel_id}")
            return

        quiz_logger.info(f"Auto-ending quiz in channel {channel_id}")

        # Calculate and display results
        await display_quiz_results(channel, channel_id)

    except asyncio.CancelledError:
        # /quiz_end cancels this task; that's expected, not an error. The
        # `except Exception` arm below would not catch this in Python 3.8+
        # (CancelledError inherits from BaseException), but be explicit so
        # the cancellation path is visible to readers.
        quiz_logger.debug(f"Auto-end task cancelled for channel {channel_id}")
        raise
    except Exception as e:
        quiz_logger.error(f"Error in auto_end_quiz for channel {channel_id}: {e}", exc_info=True)


async def display_quiz_results(channel, channel_id: int):
    """Display quiz results and clean up state."""
    quiz_logger.info(f"Displaying quiz results for channel {channel_id}")

    state = QUIZ_STATE.get(channel_id)
    if not state:
        quiz_logger.warning(f"No quiz state found for channel {channel_id}")
        return

    # Cancel the scheduled auto-end task if it hasn't already fired. Skip when
    # we *are* the auto-end task, since cancelling self raises CancelledError.
    end_task = state.get("end_task")
    if end_task and not end_task.done() and end_task is not asyncio.current_task():
        end_task.cancel()
        quiz_logger.debug(f"Cancelled scheduled auto-end task for channel {channel_id}")

    questions = state["questions"]
    user_answers = state["user_answers"]
    
    quiz_logger.info(f"Quiz results: {len(questions)} questions, {len(user_answers)} users participated")
    quiz_logger.debug(f"User answers data: {user_answers}")
    
    # Calculate scores
    scores = {}
    for user_id, answers in user_answers.items():
        score = 0
        for q_idx, choice in answers.items():
            if q_idx < len(questions):
                correct_answer = questions[q_idx]["answer"].strip().upper()
                if choice == correct_answer:
                    score += 1
        scores[user_id] = score
        quiz_logger.debug(f"User {user_id} score: {score}/{len(questions)}")
    
    # Sort by score
    scores_sorted = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    
    total_questions = len(questions)
    
    # Forest green color for embeds
    embed_color = 0x2d5016
    
    # Create leaderboard embed
    leaderboard_embed = discord.Embed(
        title="🏁 Quiz Complete!",
        color=embed_color
    )
    
    if scores_sorted:
        # Pack score lines into multiple fields if needed to stay under
        # Discord's 1024-char per-field-value limit (~20 lines per field).
        lines = [
            f"{'🥇' if i == 0 else '🥈' if i == 1 else '🥉' if i == 2 else '📊'} <@{uid}>: **{score}/{total_questions}** ({int(score/total_questions*100)}%)"
            for i, (uid, score) in enumerate(scores_sorted)
        ]
        pages: List[str] = []
        current: List[str] = []
        current_len = 0
        for line in lines:
            addition = len(line) + (1 if current else 0)  # newline separator
            if current and current_len + addition > 1024:
                pages.append("\n".join(current))
                current = [line]
                current_len = len(line)
            else:
                current.append(line)
                current_len += addition
        if current:
            pages.append("\n".join(current))
        for i, page in enumerate(pages):
            name = "Final Scores" if len(pages) == 1 else f"Final Scores ({i+1}/{len(pages)})"
            leaderboard_embed.add_field(name=name, value=page, inline=False)
        quiz_logger.info(f"Leaderboard: {[(uid, score) for uid, score in scores_sorted]}")
    else:
        leaderboard_embed.description = "No one submitted answers!"
        quiz_logger.info("No participants submitted answers")
    
    await channel.send(embed=leaderboard_embed)
    quiz_logger.info(f"Sent leaderboard embed to channel {channel_id}")
    
    # Create detailed results for each question
    for idx, q in enumerate(questions):
        quiz_logger.debug(f"Processing results for question {idx+1}/{total_questions}")
        
        result_embed = discord.Embed(
            title=f"Question {idx+1}/{total_questions}",
            description=f"**{q['q']}**",
            color=embed_color
        )
        
        # Show the correct answer
        result_embed.add_field(
            name="✅ Correct Answer",
            value=f"**{q['answer']}**",
            inline=False
        )
        
        # Collect users who answered correctly
        correct_users = []
        incorrect_users = []
        for user_id, answers in user_answers.items():
            if idx in answers:
                if answers[idx] == q["answer"].strip().upper():
                    correct_users.append(user_id)
                else:
                    incorrect_users.append(user_id)
        
        quiz_logger.info(f"Question {idx+1} results: {len(correct_users)} correct, {len(incorrect_users)} incorrect")
        quiz_logger.debug(f"Question {idx+1} correct users: {correct_users}")
        quiz_logger.debug(f"Question {idx+1} incorrect users: {incorrect_users}")
        
        # Show who answered correctly / incorrectly, chunked to stay under
        # Discord's 1024-char per-field-value limit.
        for name, value in chunk_mentions(correct_users, "✅ Answered Correctly"):
            result_embed.add_field(name=name, value=value, inline=False)
        for name, value in chunk_mentions(incorrect_users, "❌ Answered Incorrectly"):
            result_embed.add_field(name=name, value=value, inline=False)
        
        # Show explanation
        result_embed.add_field(
            name="📖 Explanation",
            value=q['explain'],
            inline=False
        )
        
        await channel.send(embed=result_embed)
        quiz_logger.debug(f"Sent results embed for question {idx+1} to channel {channel_id}")
    
    # Send closing message
    await channel.send("Start a new quiz with `/quiz_start`!")

    # Mark completed in the DB (keeps the row for history) then clean up memory.
    await _persist_completion(state)
    QUIZ_STATE.pop(channel_id, None)
    quiz_logger.info(f"Cleaned up quiz state for channel {channel_id}")


# --- Discord Commands ---

@tree.command(name="ask", description="Ask a question about the ACC documentation")
async def ask_command(interaction: discord.Interaction, question: str):
    """Ask the bot a question grounded in the uploaded PDF."""
    discord_logger.info(f"/ask command: user={interaction.user.name}({interaction.user.id}) guild={interaction.guild.name if interaction.guild else 'DM'}({interaction.guild_id if interaction.guild else 'N/A'}) channel={interaction.channel_id} question='{question[:100]}'")
    
    # Check permissions first
    has_perms, perm_error = await check_bot_permissions(interaction)
    if not has_perms:
        discord_logger.warning(f"/ask permission denied for user {interaction.user.name}({interaction.user.id}) in channel {interaction.channel_id}")
        await interaction.response.send_message(perm_error, ephemeral=True)
        return

    # Per-user rate limit so a single user can't run up cost / spam the API.
    retry_after = rate_limit_ask(interaction.user.id)
    if retry_after is not None:
        window_label = "hour" if ASK_RATE_WINDOW_SECONDS == 3600 else f"{ASK_RATE_WINDOW_SECONDS // 60} minute(s)"
        minutes, seconds = divmod(retry_after, 60)
        discord_logger.info(f"/ask rate-limited user {interaction.user.name}({interaction.user.id}); retry in {retry_after}s")
        await interaction.response.send_message(
            f"⏳ You've reached the limit of {ASK_RATE_LIMIT} `/ask` questions per {window_label}. "
            f"Try again in {minutes}m {seconds}s.",
            ephemeral=True,
        )
        return

    await interaction.response.defer(thinking=True)
    
    # Grounding/page-citation/refusal rules live in ACC_INSTRUCTIONS (the
    # cached system prompt); only the Discord-specific length constraint needs
    # to ride along per-request.
    enhanced_question = f"{question}\n\n(Keep your answer under 2000 characters so it fits in a single Discord message.)"
    
    api_logger.debug(f"Sending question to assistant API: '{enhanced_question[:100]}'")
    answer = await ask_assistant(enhanced_question)
    api_logger.debug(f"Received answer from assistant API (length={len(answer)})")

    # Discord has a 2000 character limit per message; close any open code fence
    # before truncating so markdown rendering doesn't break.
    original_len = len(answer)
    answer = truncate_for_discord(answer)
    if len(answer) != original_len:
        api_logger.warning(f"Answer truncated from {original_len} to {len(answer)} characters")

    await interaction.followup.send(answer)
    discord_logger.info(f"/ask completed for user {interaction.user.name}({interaction.user.id})")


@tree.command(name="quiz_start", description="Start a quiz from the ACC documentation. Defaults to 5 questions with a 15 minute duration.")
async def quiz_start(interaction: discord.Interaction, topic: str = "", questions: int = 5, duration: int = 15):
    """Start a new quiz session in this channel."""
    discord_logger.info(f"/quiz_start command: user={interaction.user.name}({interaction.user.id}) guild={interaction.guild.name if interaction.guild else 'DM'}({interaction.guild_id if interaction.guild else 'N/A'}) channel={interaction.channel_id} topic='{topic}' questions={questions} duration={duration}")

    # Check permissions first
    has_perms, perm_error = await check_bot_permissions(interaction)
    if not has_perms:
        discord_logger.warning(f"/quiz_start permission denied for user {interaction.user.name}({interaction.user.id}) in channel {interaction.channel_id}")
        await interaction.response.send_message(perm_error, ephemeral=True)
        return

    if questions < 1 or questions > 10:
        discord_logger.warning(f"/quiz_start invalid question count {questions} from user {interaction.user.name}({interaction.user.id})")
        await interaction.response.send_message(
            "❌ Please choose between 1 and 10 questions.",
            ephemeral=True
        )
        return

    if duration < 1 or duration > 60:
        discord_logger.warning(f"/quiz_start invalid duration {duration} from user {interaction.user.name}({interaction.user.id})")
        await interaction.response.send_message(
            "❌ Please choose a duration between 1 and 60 minutes.",
            ephemeral=True
        )
        return
    
    if interaction.channel_id in QUIZ_STATE:
        discord_logger.warning(f"/quiz_start attempted but quiz already running in channel {interaction.channel_id}")
        await interaction.response.send_message(
            "⚠️ There's already a quiz running in this channel! Finish it first or use `/quiz_end` to cancel.",
            ephemeral=True
        )
        return
    
    await interaction.response.defer(thinking=True)
    
    quiz_logger.info(f"Building quiz: topic='{topic}' questions={questions} duration={duration} for channel {interaction.channel_id}")

    # Serve from the pre-generated bank when it can satisfy the request (no API
    # call, instant). Fall back to live generation when the bank is empty/unseeded
    # or a topic filter leaves too few matches.
    quiz_questions = sample_questions(QUESTION_BANK, questions, topic)
    quiz_source = "bank"
    if len(quiz_questions) < questions:
        quiz_logger.info(
            f"Bank supplied {len(quiz_questions)}/{questions} (topic='{topic}') for channel "
            f"{interaction.channel_id}; falling back to live generation"
        )
        generated = await generate_quiz(topic_hint=topic, num_questions=questions)
        if generated:
            quiz_questions = generated
            quiz_source = "generated"
    quiz_logger.info(
        f"Quiz for channel {interaction.channel_id}: "
        f"{len(quiz_questions) if quiz_questions else 0} questions from {quiz_source}"
    )

    if not quiz_questions:
        quiz_logger.error(f"Failed to generate quiz for channel {interaction.channel_id}")
        await interaction.followup.send(
            "❌ Couldn't generate a quiz right now. Try:\n"
            "• A more specific topic\n"
            "• Fewer questions\n"
            "• Asking again in a moment"
        )
        return
    
    # Shuffle the options for each question to randomize correct answer position
    shuffled_questions = [shuffle_quiz_options(q) for q in quiz_questions]

    started_at = datetime.now(timezone.utc)
    end_time = started_at + timedelta(minutes=duration)

    # Persist the quiz before going live so it survives a restart. Best-effort:
    # if the store is down, the quiz still runs in memory (quiz_id stays None,
    # so answer/completion persistence is skipped).
    quiz_id = None
    if quiz_store is not None:
        try:
            quiz_id = await quiz_store.create_quiz(
                channel_id=interaction.channel_id,
                guild_id=interaction.guild_id,
                initiator_id=interaction.user.id,
                topic=topic,
                started_at=started_at,
                end_time=end_time,
                duration_minutes=duration,
                questions=shuffled_questions,
            )
        except Exception as e:
            quiz_logger.error(f"Failed to persist new quiz in channel {interaction.channel_id}: {e}", exc_info=True)

    QUIZ_STATE[interaction.channel_id] = {
        "questions": shuffled_questions,
        "user_answers": {},  # {user_id: {question_idx: choice}}
        "end_time": end_time,
        "duration_minutes": duration,
        "initiator": interaction.user.id,
        "quiz_id": quiz_id,
    }

    quiz_logger.info(f"Quiz started in channel {interaction.channel_id} by user {interaction.user.name}({interaction.user.id}): {len(shuffled_questions)} questions, {duration} minutes, quiz_id={quiz_id}")

    topic_text = f" (Topic: {topic})" if topic else ""

    # Schedule auto-end task and hold a strong reference in QUIZ_STATE so it
    # isn't garbage-collected mid-sleep, and so /quiz_end can cancel it.
    end_task = asyncio.create_task(
        auto_end_quiz(interaction.channel_id, interaction.channel)
    )
    QUIZ_STATE[interaction.channel_id]["end_task"] = end_task
    
    # Send initial message with embed
    start_embed = discord.Embed(
        title="✈️ Quiz Started!",
        description=f"{topic_text if topic else ''}",
        color=0x2d5016
    )
    start_embed.add_field(
        name="⏱️ Duration",
        value=f"**{duration} minute(s)**",
        inline=True
    )
    start_embed.add_field(
        name="📝 Questions",
        value=f"**{len(shuffled_questions)}**",
        inline=True
    )
    start_embed.add_field(
        name="Instructions",
        value="Click the buttons below each question to answer!\nResults will be revealed when the timer ends!",
        inline=False
    )
    
    await interaction.followup.send(embed=start_embed)
    
    # Send each question with its button options
    for idx, q in enumerate(shuffled_questions):
        question_embed = format_mcq(q["q"], q["options"], idx + 1, len(shuffled_questions))
        view = build_question_view(interaction.channel_id, idx, q["options"])
        await interaction.channel.send(embed=question_embed, view=view)
    
    quiz_logger.info(f"All quiz questions posted to channel {interaction.channel_id}")


@tree.command(name="quiz_answer", description="Answer a quiz question (alternative to buttons)")
async def quiz_answer(interaction: discord.Interaction, question_number: int, choice: str):
    """Submit an answer to a quiz question."""
    discord_logger.info(f"/quiz_answer command: user={interaction.user.name}({interaction.user.id}) guild={interaction.guild.name if interaction.guild else 'DM'}({interaction.guild_id if interaction.guild else 'N/A'}) channel={interaction.channel_id} q={question_number} choice={choice}")
    
    choice = choice.strip().upper()
    
    if choice not in ["A", "B", "C", "D"]:
        discord_logger.warning(f"/quiz_answer invalid choice '{choice}' from user {interaction.user.name}({interaction.user.id})")
        await interaction.response.send_message(
            "❌ Please answer with A, B, C, or D.",
            ephemeral=True
        )
        return
    
    state = QUIZ_STATE.get(interaction.channel_id)
    if not state:
        discord_logger.warning(f"/quiz_answer no quiz in channel {interaction.channel_id} for user {interaction.user.name}({interaction.user.id})")
        await interaction.response.send_message(
            "❌ No quiz is running in this channel. Use `/quiz_start` to begin!",
            ephemeral=True
        )
        return
    
    # Check if quiz has ended
    if datetime.now(timezone.utc) >= state["end_time"]:
        discord_logger.warning(f"/quiz_answer after quiz ended in channel {interaction.channel_id} for user {interaction.user.name}({interaction.user.id})")
        await interaction.response.send_message(
            "❌ This quiz has ended! Results are being calculated.",
            ephemeral=True
        )
        return
    
    # Validate question number
    question_idx = question_number - 1
    if question_idx < 0 or question_idx >= len(state["questions"]):
        discord_logger.error(f"/quiz_answer invalid question number {question_number} from user {interaction.user.name}({interaction.user.id}) in channel {interaction.channel_id}")
        await interaction.response.send_message(
            f"❌ Invalid question number. Please choose between 1 and {len(state['questions'])}.",
            ephemeral=True
        )
        return
    
    user_id = str(interaction.user.id)
    
    # Initialize user's answers if needed
    if user_id not in state["user_answers"]:
        state["user_answers"][user_id] = {}
        quiz_logger.debug(f"Initialized answer dict for user {interaction.user.name}({user_id}) in channel {interaction.channel_id}")
    
    # Store the answer (memory is the hot-path source of truth; mirror to DB)
    state["user_answers"][user_id][question_idx] = choice
    await _persist_answer(state, question_idx, interaction.user.id, choice)
    quiz_logger.info(f"Stored answer via command: user={interaction.user.name}({user_id}) channel={interaction.channel_id} q={question_number} answer={choice}")
    
    # Calculate how many questions they've answered
    answered_count = len(state["user_answers"][user_id])
    total_questions = len(state["questions"])
    
    minutes_remaining, seconds_remaining = format_time_remaining(state["end_time"])

    quiz_logger.debug(f"User {interaction.user.name}({user_id}) progress: {answered_count}/{total_questions} answered, {minutes_remaining}m {seconds_remaining}s remaining")

    await interaction.response.send_message(
        f"📝 Answer recorded for question {question_number}!\n"
        f"📊 You've answered {answered_count}/{total_questions} questions.\n"
        f"⏱️ Time remaining: {minutes_remaining}m {seconds_remaining}s",
        ephemeral=True
    )


@tree.command(name="quiz_end", description="End the current quiz and show results")
async def quiz_end(interaction: discord.Interaction):
    """End the current quiz and display results."""
    discord_logger.info(f"/quiz_end command: user={interaction.user.name}({interaction.user.id}) guild={interaction.guild.name if interaction.guild else 'DM'}({interaction.guild_id if interaction.guild else 'N/A'}) channel={interaction.channel_id}")
    
    # Check permissions first
    has_perms, perm_error = await check_bot_permissions(interaction)
    if not has_perms:
        discord_logger.warning(f"/quiz_end permission denied for user {interaction.user.name}({interaction.user.id}) in channel {interaction.channel_id}")
        await interaction.response.send_message(perm_error, ephemeral=True)
        return
    
    state = QUIZ_STATE.get(interaction.channel_id)
    if state is None:
        discord_logger.warning(f"/quiz_end no quiz in channel {interaction.channel_id}")
        await interaction.response.send_message(
            "❌ No quiz is running in this channel.",
            ephemeral=True
        )
        return

    # Only the initiator or a moderator (manage_messages in guild channels)
    # may end the quiz. In DMs there's no manage_messages so only the
    # initiator qualifies — which is fine since DMs are 1:1 anyway.
    initiator_id = state.get("initiator")
    is_initiator = interaction.user.id == initiator_id
    is_mod = (
        interaction.guild is not None
        and interaction.channel.permissions_for(interaction.user).manage_messages
    )
    if not (is_initiator or is_mod):
        discord_logger.warning(
            f"/quiz_end refused: user {interaction.user.name}({interaction.user.id}) is "
            f"neither initiator ({initiator_id}) nor moderator in channel {interaction.channel_id}"
        )
        await interaction.response.send_message(
            f"❌ Only the quiz initiator (<@{initiator_id}>) or a moderator can end this quiz.",
            ephemeral=True,
        )
        return

    await interaction.response.defer()

    quiz_logger.info(f"Quiz manually ended in channel {interaction.channel_id} by user {interaction.user.name}({interaction.user.id})")

    # Display results
    await display_quiz_results(interaction.channel, interaction.channel_id)

    await interaction.followup.send(
        f"🛑 Quiz ended by <@{interaction.user.id}>."
    )


@tree.command(name="quiz_score", description="Check your quiz progress")
async def quiz_score(interaction: discord.Interaction):
    """Show your current quiz progress."""
    discord_logger.debug(f"/quiz_score command: user={interaction.user.name}({interaction.user.id}) guild={interaction.guild.name if interaction.guild else 'DM'}({interaction.guild_id if interaction.guild else 'N/A'}) channel={interaction.channel_id}")
    
    state = QUIZ_STATE.get(interaction.channel_id)
    if not state:
        await interaction.response.send_message(
            "❌ No quiz is running in this channel.",
            ephemeral=True
        )
        return
    
    user_id = str(interaction.user.id)
    total_q = len(state["questions"])
    
    if user_id not in state["user_answers"]:
        answered_count = 0
    else:
        answered_count = len(state["user_answers"][user_id])
    
    minutes_remaining, seconds_remaining = format_time_remaining(state["end_time"])
    
    # Show which questions have been answered
    answered_questions = []
    if user_id in state["user_answers"]:
        answered_questions = [q_idx + 1 for q_idx in state["user_answers"][user_id].keys()]
        answered_questions.sort()
    
    answered_text = ", ".join(map(str, answered_questions)) if answered_questions else "None"
    
    discord_logger.debug(f"User {interaction.user.name}({user_id}) progress check: {answered_count}/{total_q} questions answered")
    
    await interaction.response.send_message(
        f"📊 **Your Quiz Progress:**\n"
        f"Answered: {answered_count}/{total_q} questions\n"
        f"Questions answered: {answered_text}\n"
        f"⏱️ Time remaining: {minutes_remaining}m {seconds_remaining}s",
        ephemeral=True
    )


@tree.command(name="quiz_stats", description="Show your lifetime quiz stats across completed quizzes")
async def quiz_stats(interaction: discord.Interaction):
    """Show the calling user's aggregate performance from quiz history."""
    discord_logger.info(f"/quiz_stats command: user={interaction.user.name}({interaction.user.id}) guild={interaction.guild.name if interaction.guild else 'DM'}({interaction.guild_id if interaction.guild else 'N/A'}) channel={interaction.channel_id}")

    has_perms, perm_error = await check_bot_permissions(interaction)
    if not has_perms:
        await interaction.response.send_message(perm_error, ephemeral=True)
        return

    # Stats live in the persistence layer; if it's down there's nothing to show.
    if quiz_store is None:
        await interaction.response.send_message(
            "❌ Quiz history isn't available right now (persistence is offline).",
            ephemeral=True,
        )
        return

    try:
        stats = await quiz_store.get_user_stats(interaction.user.id)
    except Exception as e:
        quiz_logger.error(f"Failed to load stats for user {interaction.user.id}: {e}", exc_info=True)
        await interaction.response.send_message(
            "❌ Couldn't load your stats right now. Try again in a moment.",
            ephemeral=True,
        )
        return

    if stats["answered"] == 0:
        await interaction.response.send_message(
            "📊 You haven't answered any questions in a completed quiz yet — "
            "jump into a `/quiz_start`!",
            ephemeral=True,
        )
        return

    accuracy_pct = round(stats["accuracy"] * 100)
    embed = discord.Embed(title="📊 Your Quiz Stats", color=0x2d5016)
    embed.add_field(name="Quizzes", value=str(stats["quizzes"]), inline=True)
    embed.add_field(name="Questions Answered", value=str(stats["answered"]), inline=True)
    embed.add_field(name="Correct", value=f"{stats['correct']} ({accuracy_pct}%)", inline=True)
    embed.set_footer(text="Across completed quizzes")

    await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.command(name="leaderboard", description="Show this server's top quiz scorers")
async def leaderboard_command(interaction: discord.Interaction):
    """Show the top scorers across completed quizzes in this server."""
    discord_logger.info(f"/leaderboard command: user={interaction.user.name}({interaction.user.id}) guild={interaction.guild.name if interaction.guild else 'DM'}({interaction.guild_id if interaction.guild else 'N/A'}) channel={interaction.channel_id}")

    has_perms, perm_error = await check_bot_permissions(interaction)
    if not has_perms:
        await interaction.response.send_message(perm_error, ephemeral=True)
        return

    # Leaderboard is per-server; there's no guild to rank within a DM.
    if interaction.guild_id is None:
        await interaction.response.send_message(
            "❌ The leaderboard is only available in a server.",
            ephemeral=True,
        )
        return

    if quiz_store is None:
        await interaction.response.send_message(
            "❌ Quiz history isn't available right now (persistence is offline).",
            ephemeral=True,
        )
        return

    try:
        rows = await quiz_store.get_leaderboard(interaction.guild_id)
    except Exception as e:
        quiz_logger.error(f"Failed to load leaderboard for guild {interaction.guild_id}: {e}", exc_info=True)
        await interaction.response.send_message(
            "❌ Couldn't load the leaderboard right now. Try again in a moment.",
            ephemeral=True,
        )
        return

    if not rows:
        await interaction.response.send_message(
            "📊 No completed quizzes yet — start one with `/quiz_start`!",
            ephemeral=True,
        )
        return

    # Mentions inside an embed render as names without pinging anyone.
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for i, r in enumerate(rows):
        rank = medals[i] if i < len(medals) else f"**{i + 1}.**"
        accuracy_pct = round(r["accuracy"] * 100)
        lines.append(
            f"{rank} <@{r['user_id']}> — **{r['correct']}** correct "
            f"({accuracy_pct}%, {r['quizzes']} quiz(zes))"
        )

    embed = discord.Embed(
        title="🏆 Quiz Leaderboard",
        description="\n".join(lines),
        color=0x2d5016,
    )
    embed.set_footer(text="Top scorers across completed quizzes")

    await interaction.response.send_message(embed=embed)


@tree.command(name="info", description="Show bot information and stats")
async def info_command(interaction: discord.Interaction):
    """Display bot information."""
    discord_logger.debug(f"/info command: user={interaction.user.name}({interaction.user.id}) guild={interaction.guild.name if interaction.guild else 'DM'}({interaction.guild_id if interaction.guild else 'N/A'}) channel={interaction.channel_id}")
    
    # Check permissions first
    has_perms, perm_error = await check_bot_permissions(interaction)
    if not has_perms:
        await interaction.response.send_message(perm_error, ephemeral=True)
        return
    
    embed = discord.Embed(
        title="✈️ DarkstarAIC",
        description="AI-powered Q&A and quiz bot for Air Control Communication",
        color=0x2d5016  # Forest green
    )
    embed.add_field(name="Model", value=CLAUDE_MODEL, inline=True)
    embed.add_field(name="Servers", value=str(len(client.guilds)), inline=True)
    embed.add_field(name="Version", value="1.0.0", inline=True)
    embed.add_field(
        name="Commands",
        value=(
            "• `/ask` - Ask questions about the documentation\n"
            "• `/quiz_start` - Start a timed quiz (1-60 min, 1-10 questions)\n"
            "• `/quiz_answer` - Submit an answer by question number (alternative to buttons)\n"
            "• `/quiz_score` - View your progress in the running quiz\n"
            "• `/quiz_stats` - View your lifetime quiz stats\n"
            "• `/leaderboard` - Show this server's top quiz scorers\n"
            "• `/quiz_end` - End the running quiz (initiator/mod only)\n"
            "• `/info` - Show this info panel"
        ),
        inline=False
    )
    embed.set_footer(text="Powered by the Anthropic Claude API")

    await interaction.response.send_message(embed=embed)


async def _resolve_channel(channel_id: int):
    """Get a channel object from cache, falling back to a fetch."""
    channel = client.get_channel(channel_id)
    if channel is not None:
        return channel
    try:
        return await client.fetch_channel(channel_id)
    except Exception:
        return None


async def rehydrate_quizzes():
    """
    Restore active quizzes from SQLite into QUIZ_STATE after a restart.

    Each restored quiz re-arms its auto-end timer for the *remaining* time
    (auto_end_quiz derives the sleep from end_time). A quiz whose end_time
    passed during downtime is finalized immediately. Answer buttons on messages
    posted before the restart keep working: their handler is re-registered in
    on_ready via add_dynamic_items(QuizAnswerButton), and the callback reads the
    QUIZ_STATE this function restores. `/quiz_answer` remains as a fallback.
    """
    if quiz_store is None:
        return
    try:
        active = await quiz_store.load_active_quizzes()
    except Exception as e:
        quiz_logger.error(f"Failed to load active quizzes for rehydration: {e}", exc_info=True)
        return

    quiz_logger.info(f"Rehydrating {len(active)} active quiz(es) from {DARKSTAR_DB_PATH}")
    for q in active:
        channel_id = q["channel_id"]
        if channel_id in QUIZ_STATE:
            continue  # already live (defensive; shouldn't happen on a fresh start)

        state = {
            "questions": q["questions"],
            # DB returns answers keyed by int user_id; the in-memory format
            # keys by str(user_id) with int question positions.
            "user_answers": {str(uid): dict(pos) for uid, pos in q["answers"].items()},
            "end_time": q["end_time"],
            "duration_minutes": q["duration_minutes"],
            "initiator": q["initiator_id"],
            "quiz_id": q["quiz_id"],
        }
        QUIZ_STATE[channel_id] = state

        channel = await _resolve_channel(channel_id)
        if channel is None:
            quiz_logger.warning(
                f"Rehydrate: channel {channel_id} unreachable; completing quiz {q['quiz_id']}"
            )
            await _persist_completion(state)
            QUIZ_STATE.pop(channel_id, None)
            continue

        remaining = (q["end_time"] - datetime.now(timezone.utc)).total_seconds()
        if remaining > 0:
            task = asyncio.create_task(auto_end_quiz(channel_id, channel))
            state["end_task"] = task
            quiz_logger.info(
                f"Rehydrated quiz {q['quiz_id']} in channel {channel_id}, {remaining:.0f}s remaining"
            )
        else:
            quiz_logger.info(
                f"Rehydrated quiz {q['quiz_id']} in channel {channel_id} expired during downtime; finalizing"
            )
            await display_quiz_results(channel, channel_id)


@client.event
async def on_ready():
    """Called when the bot is ready."""
    global quiz_store, _startup_done
    await tree.sync()
    discord_logger.info("✈️ DarkstarAIC is online!")
    discord_logger.info(f"📚 Connected to {len(client.guilds)} server(s)")
    discord_logger.info(f"🤖 Using {CLAUDE_MODEL} via Anthropic Claude API")
    if ACC_DOCUMENT_TEXT:
        discord_logger.info(f"📄 ACC document loaded: {len(ACC_DOCUMENT_TEXT):,} chars from {ACC_DOCUMENT_PATH}")
    else:
        discord_logger.error(
            f"📄 ACC document is EMPTY (expected at {ACC_DOCUMENT_PATH}). "
            f"Run scripts/extract_pdf.py and commit the output — /ask and /quiz "
            f"will be ungrounded until then."
        )
    if QUESTION_BANK:
        discord_logger.info(f"🎯 Question bank loaded: {len(QUESTION_BANK)} questions from {ACC_QUESTIONS_PATH}")
    else:
        discord_logger.warning(
            f"🎯 Question bank empty (expected at {ACC_QUESTIONS_PATH}); /quiz_start will "
            f"generate questions live. Seed it with scripts/generate_quiz_bank.py."
        )
    discord_logger.info(f"Bot user: {client.user.name}#{client.user.discriminator} (ID: {client.user.id})")

    # Log guild information
    for guild in client.guilds:
        discord_logger.info(f"  - Guild: {guild.name} (ID: {guild.id}, Members: {guild.member_count})")

    # Open the quiz store and restore in-flight quizzes — once, even if
    # on_ready fires again on a gateway reconnect.
    if not _startup_done:
        _startup_done = True
        # Re-attach answer-button handling to messages posted before this
        # process started, so buttons keep working across a restart/redeploy.
        client.add_dynamic_items(QuizAnswerButton)
        discord_logger.info("🔘 Registered persistent quiz answer buttons")
        try:
            quiz_store = await db.QuizStore.connect(DARKSTAR_DB_PATH)
            discord_logger.info(f"🗄️  Quiz store opened at {DARKSTAR_DB_PATH}")
        except Exception as e:
            discord_logger.error(
                f"Failed to open quiz store at {DARKSTAR_DB_PATH}: {e} — "
                f"running in-memory only (quizzes won't survive restarts)",
                exc_info=True,
            )
            quiz_store = None
        await rehydrate_quizzes()

    print("✈️ DarkstarAIC is online!")
    print(f"📚 Connected to {len(client.guilds)} server(s)")
    print(f"🤖 Using {CLAUDE_MODEL} via Anthropic Claude API")


if __name__ == "__main__":
    client.run(DISCORD_TOKEN)
