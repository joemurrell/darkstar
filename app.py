"""
DarkstarAIC - DCS Air Control Communication Discord Bot
PDF-grounded Q&A and Quiz system using OpenAI Assistants API (GPT-3.5-turbo)
"""
import os
import asyncio
import json
import re
from typing import List, Optional
from datetime import datetime, timedelta
import discord
from discord import app_commands
from openai import OpenAI

# Environment variables
DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
ASSISTANT_ID = os.environ["ASSISTANT_ID"]

# --- Discord client setup ---
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# --- OpenAI client (with v2 assistants) ---
oai = OpenAI(
    api_key=OPENAI_API_KEY,
    default_headers={"OpenAI-Beta": "assistants=v2"}
)

# In-memory quiz state (per-channel)
QUIZ_STATE = {}


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
        state = QUIZ_STATE.get(interaction.channel_id)
        if not state:
            await interaction.response.send_message(
                "❌ No quiz is running in this channel.",
                ephemeral=True
            )
            return
        
        # Check if quiz has ended
        if datetime.utcnow() >= state["end_time"]:
            await interaction.response.send_message(
                "❌ This quiz has ended! Results are being calculated.",
                ephemeral=True
            )
            return
        
        # Validate question number
        if self.question_idx < 0 or self.question_idx >= len(state["questions"]):
            await interaction.response.send_message(
                f"❌ Invalid question.",
                ephemeral=True
            )
            return
        
        user_id = str(interaction.user.id)
        
        # Initialize user's answers if needed
        if user_id not in state["user_answers"]:
            state["user_answers"][user_id] = {}
        
        # Store the answer
        state["user_answers"][user_id][self.question_idx] = self.choice
        
        # Calculate how many questions they've answered
        answered_count = len(state["user_answers"][user_id])
        total_questions = len(state["questions"])
        
        time_remaining = state["end_time"] - datetime.utcnow()
        minutes_remaining = int(time_remaining.total_seconds() / 60)
        seconds_remaining = int(time_remaining.total_seconds() % 60)
        
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

async def ask_assistant(user_msg: str, timeout: int = 30) -> str:
    """
    Ask the OpenAI Assistant a question using Assistants API v2.
    Uses File Search to ground responses in the uploaded PDF.
    """
    try:
        # Create a new thread for this question
        thread = oai.beta.threads.create()
        
        # Add user message to thread
        oai.beta.threads.messages.create(
            thread_id=thread.id,
            role="user",
            content=user_msg
        )
        
        # Create and run the assistant (v2 API)
        run = oai.beta.threads.runs.create(
            thread_id=thread.id,
            assistant_id=ASSISTANT_ID
        )
        
        # Poll until complete (with timeout)
        elapsed = 0
        while elapsed < timeout:
            run = oai.beta.threads.runs.retrieve(
                thread_id=thread.id,
                run_id=run.id
            )
            
            if run.status in ("completed", "failed", "cancelled", "expired"):
                break
                
            await asyncio.sleep(0.7)
            elapsed += 0.7
        
        if run.status != "completed":
            return f"⚠️ Assistant didn't respond in time (status: {run.status}). Try again."
        
        # Retrieve messages
        messages = oai.beta.threads.messages.list(thread_id=thread.id)
        
        # Find the latest assistant message
        for msg in messages.data:
            if msg.role == "assistant":
                chunks = []
                for content in msg.content:
                    if content.type == "text":
                        text = content.text.value
                        # Remove citation markers like 【4:2†source】
                        text = re.sub(r'【[^】]*】', '', text)
                        chunks.append(text)
                
                return "\n".join(chunks) if chunks else "No response from assistant."
        
        return "No response from assistant."
        
    except Exception as e:
        print(f"Error asking assistant: {e}")
        return f"❌ Error communicating with AI: {str(e)}"


def format_mcq(question: str, options: List[str], question_num: int = None, total: int = None) -> discord.Embed:
    """Format a multiple choice question as a Discord embed with forest green border."""
    letters = ["A", "B", "C", "D", "E", "F"][:len(options)]
    
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
    options_text = "\n".join(f"**{letter})** {opt}" for letter, opt in zip(letters, options))
    embed.add_field(name="Options", value=options_text, inline=False)
    
    return embed


async def generate_quiz(topic_hint: str = "", num_questions: int = 6) -> Optional[List[dict]]:
    """
    Generate a quiz from the PDF using the Assistant.
    Returns a list of question dicts or None on failure.
    """
    prompt = f"""Generate {num_questions} multiple-choice questions based ONLY on the attached PDF.

Requirements:
- Each question must have exactly 4 options
- Include the correct answer (A, B, C, or D)
- Provide a brief explanation with page number citation
- Focus on practical knowledge for DCS pilots

{f'Topic focus: {topic_hint}' if topic_hint else 'Cover various topics from the document.'}

Return ONLY a valid JSON array with this exact structure:
[
  {{
    "q": "Question text here?",
    "options": ["Option A text", "Option B text", "Option C text", "Option D text"],
    "answer": "A",
    "explain": "Brief explanation with page reference (p.XX)"
  }}
]

IMPORTANT: Return ONLY the JSON array, no other text."""

    reply = await ask_assistant(prompt, timeout=45)
    
    try:
        # Try to extract JSON from the response
        reply_clean = reply.strip()
        if reply_clean.startswith("```json"):
            reply_clean = reply_clean[7:]
        if reply_clean.startswith("```"):
            reply_clean = reply_clean[3:]
        if reply_clean.endswith("```"):
            reply_clean = reply_clean[:-3]
        
        reply_clean = reply_clean.strip()
        
        data = json.loads(reply_clean)
        
        # Validate questions
        valid_questions = []
        for item in data:
            if all(k in item for k in ("q", "options", "answer", "explain")):
                if len(item["options"]) == 4:
                    item["answer"] = item["answer"].strip().upper()
                    if item["answer"] in ["A", "B", "C", "D"]:
                        valid_questions.append(item)
        
        return valid_questions[:num_questions] if valid_questions else None
        
    except json.JSONDecodeError as e:
        print(f"JSON parse error: {e}")
        print(f"Response was: {reply[:500]}")
        return None
    except Exception as e:
        print(f"Quiz generation error: {e}")
        return None


async def auto_end_quiz(channel_id: int, channel, duration_minutes: int):
    """Automatically end the quiz after the specified duration."""
    try:
        await asyncio.sleep(duration_minutes * 60)
        
        # Check if quiz still exists
        state = QUIZ_STATE.get(channel_id)
        if not state:
            return
        
        # Calculate and display results
        await display_quiz_results(channel, channel_id)
        
    except Exception as e:
        print(f"Error in auto_end_quiz: {e}")


async def display_quiz_results(channel, channel_id: int):
    """Display quiz results and clean up state."""
    state = QUIZ_STATE.get(channel_id)
    if not state:
        return
    
    questions = state["questions"]
    user_answers = state["user_answers"]
    
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
        leaderboard_text = "\n".join(
            f"{'🥇' if i == 0 else '🥈' if i == 1 else '🥉' if i == 2 else '📊'} <@{uid}>: **{score}/{total_questions}** ({int(score/total_questions*100)}%)"
            for i, (uid, score) in enumerate(scores_sorted)
        )
        leaderboard_embed.add_field(name="Final Scores", value=leaderboard_text, inline=False)
    else:
        leaderboard_embed.description = "No one submitted answers!"
    
    await channel.send(embed=leaderboard_embed)
    
    # Create detailed results for each question
    for idx, q in enumerate(questions):
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
        
        # Show who answered correctly
        if correct_users:
            correct_mentions = ", ".join(f"<@{uid}>" for uid in correct_users)
            result_embed.add_field(
                name="✅ Answered Correctly",
                value=correct_mentions,
                inline=False
            )
        
        # Show who answered incorrectly
        if incorrect_users:
            incorrect_mentions = ", ".join(f"<@{uid}>" for uid in incorrect_users)
            result_embed.add_field(
                name="❌ Answered Incorrectly",
                value=incorrect_mentions,
                inline=False
            )
        
        # Show explanation
        result_embed.add_field(
            name="📖 Explanation",
            value=q['explain'],
            inline=False
        )
        
        await channel.send(embed=result_embed)
    
    # Send closing message
    await channel.send("Start a new quiz with `/quiz_start`!")
    
    # Clean up state
    QUIZ_STATE.pop(channel_id, None)


# --- Discord Commands ---

@tree.command(name="ask", description="Ask a question about the ACC documentation")
async def ask_command(interaction: discord.Interaction, question: str):
    """Ask the bot a question grounded in the uploaded PDF."""
    await interaction.response.defer(thinking=True)
    
    enhanced_question = f"{question}\n\n(Answer using ONLY information from the attached PDF documentation. Include page numbers when possible. If the answer isn't in the PDF, say so clearly.)"
    
    answer = await ask_assistant(enhanced_question)
    
    # Discord has a 2000 character limit
    if len(answer) > 1900:
        answer = answer[:1897] + "..."
    
    await interaction.followup.send(answer)


@tree.command(name="quiz_start", description="Start a quiz from the ACC documentation")
async def quiz_start(interaction: discord.Interaction, topic: str = "", questions: int = 6, duration: int = 5):
    """Start a new quiz session in this channel."""
    if questions < 3 or questions > 10:
        await interaction.response.send_message(
            "❌ Please choose between 3 and 10 questions.",
            ephemeral=True
        )
        return
    
    if duration < 1 or duration > 60:
        await interaction.response.send_message(
            "❌ Please choose a duration between 1 and 60 minutes.",
            ephemeral=True
        )
        return
    
    if interaction.channel_id in QUIZ_STATE:
        await interaction.response.send_message(
            "⚠️ There's already a quiz running in this channel! Finish it first or use `/quiz_end` to cancel.",
            ephemeral=True
        )
        return
    
    await interaction.response.defer(thinking=True)
    
    quiz_questions = await generate_quiz(topic_hint=topic, num_questions=questions)
    
    if not quiz_questions:
        await interaction.followup.send(
            "❌ Couldn't generate a quiz right now. Try:\n"
            "• A more specific topic\n"
            "• Fewer questions\n"
            "• Asking again in a moment"
        )
        return
    
    end_time = datetime.utcnow() + timedelta(minutes=duration)
    
    QUIZ_STATE[interaction.channel_id] = {
        "questions": quiz_questions,
        "user_answers": {},  # {user_id: {question_idx: choice}}
        "end_time": end_time,
        "duration_minutes": duration,
        "initiator": interaction.user.id
    }
    
    topic_text = f" (Topic: {topic})" if topic else ""
    
    # Schedule auto-end task
    asyncio.create_task(auto_end_quiz(interaction.channel_id, interaction.channel, duration))
    
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
        value=f"**{len(quiz_questions)}**",
        inline=True
    )
    start_embed.add_field(
        name="Instructions",
        value="Click the buttons below each question to answer!\nResults will be revealed when the timer ends!",
        inline=False
    )
    
    await interaction.followup.send(embed=start_embed)
    
    # Send each question with its button options
    for idx, q in enumerate(quiz_questions):
        question_embed = format_mcq(q["q"], q["options"], idx + 1, len(quiz_questions))
        view = QuizQuestionView(idx, q["options"])
        await interaction.channel.send(embed=question_embed, view=view)


@tree.command(name="quiz_answer", description="Answer a quiz question (alternative to buttons)")
async def quiz_answer(interaction: discord.Interaction, question_number: int, choice: str):
    """Submit an answer to a quiz question."""
    choice = choice.strip().upper()
    
    if choice not in ["A", "B", "C", "D"]:
        await interaction.response.send_message(
            "❌ Please answer with A, B, C, or D.",
            ephemeral=True
        )
        return
    
    state = QUIZ_STATE.get(interaction.channel_id)
    if not state:
        await interaction.response.send_message(
            "❌ No quiz is running in this channel. Use `/quiz_start` to begin!",
            ephemeral=True
        )
        return
    
    # Check if quiz has ended
    if datetime.utcnow() >= state["end_time"]:
        await interaction.response.send_message(
            "❌ This quiz has ended! Results are being calculated.",
            ephemeral=True
        )
        return
    
    # Validate question number
    question_idx = question_number - 1
    if question_idx < 0 or question_idx >= len(state["questions"]):
        await interaction.response.send_message(
            f"❌ Invalid question number. Please choose between 1 and {len(state['questions'])}.",
            ephemeral=True
        )
        return
    
    user_id = str(interaction.user.id)
    
    # Initialize user's answers if needed
    if user_id not in state["user_answers"]:
        state["user_answers"][user_id] = {}
    
    # Store the answer
    state["user_answers"][user_id][question_idx] = choice
    
    # Calculate how many questions they've answered
    answered_count = len(state["user_answers"][user_id])
    total_questions = len(state["questions"])
    
    time_remaining = state["end_time"] - datetime.utcnow()
    minutes_remaining = int(time_remaining.total_seconds() / 60)
    seconds_remaining = int(time_remaining.total_seconds() % 60)
    
    await interaction.response.send_message(
        f"📝 Answer recorded for question {question_number}!\n"
        f"📊 You've answered {answered_count}/{total_questions} questions.\n"
        f"⏱️ Time remaining: {minutes_remaining}m {seconds_remaining}s",
        ephemeral=True
    )


@tree.command(name="quiz_end", description="End the current quiz and show results")
async def quiz_end(interaction: discord.Interaction):
    """End the current quiz and display results."""
    if interaction.channel_id not in QUIZ_STATE:
        await interaction.response.send_message(
            "❌ No quiz is running in this channel.",
            ephemeral=True
        )
        return
    
    await interaction.response.defer()
    
    # Display results
    await display_quiz_results(interaction.channel, interaction.channel_id)
    
    await interaction.followup.send("🛑 Quiz ended by moderator.")


@tree.command(name="quiz_score", description="Check your quiz progress")
async def quiz_score(interaction: discord.Interaction):
    """Show your current quiz progress."""
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
    
    time_remaining = state["end_time"] - datetime.utcnow()
    minutes_remaining = max(0, int(time_remaining.total_seconds() / 60))
    seconds_remaining = max(0, int(time_remaining.total_seconds() % 60))
    
    # Show which questions have been answered
    answered_questions = []
    if user_id in state["user_answers"]:
        answered_questions = [q_idx + 1 for q_idx in state["user_answers"][user_id].keys()]
        answered_questions.sort()
    
    answered_text = ", ".join(map(str, answered_questions)) if answered_questions else "None"
    
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
    embed = discord.Embed(
        title="✈️ DarkstarAIC",
        description="AI-powered Q&A and quiz bot for Air Control Communication",
        color=discord.Color.blue()
    )
    embed.add_field(name="Model", value="GPT-3.5-turbo", inline=True)
    embed.add_field(name="Servers", value=str(len(client.guilds)), inline=True)
    embed.add_field(name="Version", value="1.0.2", inline=True)
    embed.add_field(
        name="Commands",
        value="• `/ask` - Ask questions\n• `/quiz_start` - Start timed quiz\n• `/quiz_answer` - Answer question\n• `/quiz_score` - View progress\n• `/quiz_end` - End quiz",
        inline=False
    )
    embed.set_footer(text="Powered by OpenAI Assistants API v2")
    
    await interaction.response.send_message(embed=embed)


@client.event
async def on_ready():
    """Called when the bot is ready."""
    await tree.sync()
    print(f"✈️ DarkstarAIC is online!")
    print(f"📚 Connected to {len(client.guilds)} server(s)")
    print(f"🤖 Using GPT-3.5-turbo with Assistants API v2")


if __name__ == "__main__":
    client.run(DISCORD_TOKEN)
