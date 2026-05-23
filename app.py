"""
DarkstarAIC - DCS Air Control Communication Discord Bot
PDF-grounded Q&A and Quiz system using the Anthropic Claude API
(Files API for PDF attachment + prompt caching + tool-use structured output).
"""
import os
import asyncio
import random
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Set, Tuple, Union
from collections import Counter
from difflib import SequenceMatcher
import re
import discord
from discord import app_commands
from anthropic import AsyncAnthropic, APITimeoutError

# Environment variables
DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
# File ID returned by Anthropic's Files API for the ACC reference PDF.
# Upload once with scripts/upload_pdf.py and set the resulting value here.
ACC_FILE_ID = os.environ["ACC_FILE_ID"]
# Claude model to use. Defaults to Haiku 4.5 for cost; bump to
# claude-sonnet-4-6 for higher-quality quiz generation.
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5")

# --- Discord client setup ---
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# --- Anthropic client ---
anthropic_client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

# Beta header required for the Files API (PDF attachment via file_id).
ANTHROPIC_BETAS = ["files-api-2025-04-14"]

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

# In-memory quiz state (per-channel)
QUIZ_STATE = {}

# System prompt — defines DarkstarAIC's persona and grounding rules. Edit
# directly to tune tone or refusal behavior; the value is cached prefix so
# changes invalidate the prompt cache until the new prefix is re-warmed.
ACC_INSTRUCTIONS = """You are DarkstarAIC, an AI assistant for a DCS (Digital Combat Simulator World) flight squadron. You help squadron members learn and practice the concepts, terminology, and application of the Air Control Communication (ACC) multi-Service tactics, techniques, and procedures (MTTP) publication — more commonly known as air intercept control, C2, or AWACS.

Grounding rules:
- Answer only from the ACC PDF attached to this conversation. If the answer is not in the PDF, say exactly: "That information is not available in the ACC documentation."
- Cite page numbers inline (e.g. "see p. 42") whenever you reference a procedure.
- Use proper military aviation terminology. Be concise but thorough, and don't soften technical detail.

When generating quizzes:
- Build realistic scenarios with proper context that test the knowledge controllers and pilots actually need.
- Make every question cover a distinct concept — don't repeat the same terminology across questions.
- Write distractors that are plausible to a novice but unambiguously wrong to someone who knows the material.
- Always explain the correct answer and include its page reference."""


# --- Button Classes for Quiz Interaction ---

class QuizAnswerButton(discord.ui.Button):
    """Button for answering a quiz question."""
    
    def __init__(self, question_idx: int, choice: str, label: str):
        super().__init__(
            style=discord.ButtonStyle.primary,
            label=f"{choice}",
            custom_id=f"quiz_{question_idx}_{choice}"
        )
        self.question_idx = question_idx
        self.choice = choice
    
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
        
        # Store the answer
        state["user_answers"][user_id][self.question_idx] = self.choice
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


class QuizQuestionView(discord.ui.View):
    """View containing buttons for a quiz question."""
    
    def __init__(self, question_idx: int, options: List[str]):
        super().__init__(timeout=None)  # No timeout since quiz has its own timer
        
        # Add buttons for each option (A, B, C, D)
        choices = ["A", "B", "C", "D"]
        for i, (choice, option_text) in enumerate(zip(choices[:len(options)], options)):
            button = QuizAnswerButton(question_idx, choice, option_text)
            self.add_item(button)


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


async def ask_assistant(
    user_msg: str,
    timeout: int = 30,
    temperature: Optional[float] = None,
    tool: Optional[dict] = None,
) -> Union[str, dict, None]:
    """
    Ask Claude a question grounded in the ACC PDF (attached via Files API).

    System prompt and PDF are both marked with `cache_control: ephemeral`
    so the ~50K-token prefix is served from cache on every request after
    the first one in a 5-minute window.

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
        # System prompt is cached so the ~5-min window covers a typical
        # interactive session at near-zero cost.
        "system": [
            {
                "type": "text",
                "text": ACC_INSTRUCTIONS,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "messages": [
            {
                "role": "user",
                "content": [
                    # PDF goes first in the user message so a cache breakpoint
                    # on it covers the whole ~50K-token prefix; the varying
                    # user question lands after the breakpoint.
                    {
                        "type": "document",
                        "source": {"type": "file", "file_id": ACC_FILE_ID},
                        "cache_control": {"type": "ephemeral"},
                    },
                    {"type": "text", "text": user_msg},
                ],
            }
        ],
        "betas": ANTHROPIC_BETAS,
    }

    if temperature is not None and model_supports_temperature(CLAUDE_MODEL):
        request_params["temperature"] = temperature

    if tool is not None:
        request_params["tools"] = [tool]
        request_params["tool_choice"] = {"type": "tool", "name": tool["name"]}
        # Give forced tool-use plenty of room — quiz schemas with N questions
        # generate a few KB of structured output.
        request_params["max_tokens"] = 16000

    try:
        response = await anthropic_client.beta.messages.create(
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
            api_logger.warning(f"Forced tool {tool['name']} but no tool_use block in response")
            return None

        # Plain-text path: concatenate text blocks.
        chunks = [block.text for block in response.content if block.type == "text"]
        if not chunks:
            api_logger.warning("No text content found in response")
            return "No response from assistant."

        result = "\n".join(chunks)
        api_logger.info(f"Assistant response received: length={len(result)}")
        return result

    except APITimeoutError:
        api_logger.error(f"Anthropic request timed out after {timeout}s")
        msg = "❌ The AI took too long to respond. Please try again in a moment."
        return None if tool is not None else msg
    except Exception as e:
        api_logger.error(f"Error asking assistant: {e}", exc_info=True)
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
        "Submit a set of multiple-choice quiz questions about the attached "
        "ACC PDF. Every question must have exactly 4 options, a correct "
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


async def _request_quiz_questions(prompt: str, temperature: float) -> List[dict]:
    """Single quiz-generation API call. Returns validated questions or []."""
    result = await ask_assistant(
        prompt, timeout=45, temperature=temperature, tool=QUIZ_TOOL,
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
        f"Generate {num_questions} multiple-choice questions based ONLY on the attached ACC PDF.\n\n"
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
                f"Generate {needed + 2} additional multiple-choice questions based ONLY on the attached ACC PDF.\n\n"
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


async def auto_end_quiz(channel_id: int, channel, duration_minutes: int):
    """Automatically end the quiz after the specified duration."""
    quiz_logger.info(f"Auto-end task started for channel {channel_id}, will end in {duration_minutes} minutes")
    
    try:
        await asyncio.sleep(duration_minutes * 60)

        # Check if quiz still exists
        state = QUIZ_STATE.get(channel_id)
        if not state:
            quiz_logger.warning(f"Auto-end: quiz no longer exists in channel {channel_id}")
            return

        quiz_logger.info(f"Auto-ending quiz in channel {channel_id} after {duration_minutes} minutes")

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
    
    # Clean up state
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
    
    quiz_logger.info(f"Generating quiz: topic='{topic}' questions={questions} duration={duration} for channel {interaction.channel_id}")
    quiz_questions = await generate_quiz(topic_hint=topic, num_questions=questions)
    
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
    
    end_time = datetime.now(timezone.utc) + timedelta(minutes=duration)
    
    QUIZ_STATE[interaction.channel_id] = {
        "questions": shuffled_questions,
        "user_answers": {},  # {user_id: {question_idx: choice}}
        "end_time": end_time,
        "duration_minutes": duration,
        "initiator": interaction.user.id
    }
    
    quiz_logger.info(f"Quiz started in channel {interaction.channel_id} by user {interaction.user.name}({interaction.user.id}): {len(shuffled_questions)} questions, {duration} minutes")

    topic_text = f" (Topic: {topic})" if topic else ""

    # Schedule auto-end task and hold a strong reference in QUIZ_STATE so it
    # isn't garbage-collected mid-sleep, and so /quiz_end can cancel it.
    end_task = asyncio.create_task(
        auto_end_quiz(interaction.channel_id, interaction.channel, duration)
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
        view = QuizQuestionView(idx, q["options"])
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
    
    # Store the answer
    state["user_answers"][user_id][question_idx] = choice
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
            "• `/quiz_end` - End the running quiz (initiator/mod only)\n"
            "• `/info` - Show this info panel"
        ),
        inline=False
    )
    embed.set_footer(text="Powered by the Anthropic Claude API")

    await interaction.response.send_message(embed=embed)


@client.event
async def on_ready():
    """Called when the bot is ready."""
    await tree.sync()
    discord_logger.info("✈️ DarkstarAIC is online!")
    discord_logger.info(f"📚 Connected to {len(client.guilds)} server(s)")
    discord_logger.info(f"🤖 Using {CLAUDE_MODEL} via Anthropic Claude API (file_id={ACC_FILE_ID})")
    discord_logger.info(f"Bot user: {client.user.name}#{client.user.discriminator} (ID: {client.user.id})")

    # Log guild information
    for guild in client.guilds:
        discord_logger.info(f"  - Guild: {guild.name} (ID: {guild.id}, Members: {guild.member_count})")

    print("✈️ DarkstarAIC is online!")
    print(f"📚 Connected to {len(client.guilds)} server(s)")
    print(f"🤖 Using {CLAUDE_MODEL} via Anthropic Claude API")


if __name__ == "__main__":
    client.run(DISCORD_TOKEN)
