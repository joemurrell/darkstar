"""
DarkstarAIC - DCS Squadron Discord Bot
PDF-grounded Q&A and Quiz system using OpenAI Assistants API (GPT-3.5-turbo)
"""
import os
import asyncio
import json
import random
from typing import List, Optional
import discord
from discord import app_commands
from fastapi import FastAPI
import uvicorn
from openai import OpenAI

# Environment variables
DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
ASSISTANT_ID = os.environ["ASSISTANT_ID"]

# --- Web server for Railway health checks ---
api = FastAPI()

@api.get("/")
def health_check():
    return {"status": "ok", "bot": "DarkstarAIC", "version": "1.0.0"}

@api.get("/health")
def health():
    return {"healthy": True, "service": "DarkstarAIC"}

# --- Discord client setup ---
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# --- OpenAI client ---
oai = OpenAI(api_key=OPENAI_API_KEY)

# In-memory quiz state (per-channel)
QUIZ_STATE = {}

# --- Helper Functions ---

async def ask_assistant(user_msg: str, timeout: int = 30) -> str:
    """
    Ask the OpenAI Assistant a question.
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
        
        # Create and run the assistant
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
                        chunks.append(content.text.value)
                return "\n".join(chunks) if chunks else "No response from assistant."
        
        return "No response from assistant."
        
    except Exception as e:
        print(f"Error asking assistant: {e}")
        return f"❌ Error communicating with AI: {str(e)}"


def format_mcq(question: str, options: List[str], question_num: int = None, total: int = None) -> str:
    """Format a multiple choice question for Discord."""
    letters = ["A", "B", "C", "D", "E", "F"][:len(options)]
    
    header = ""
    if question_num is not None and total is not None:
        header = f"**Question {question_num}/{total}**\n"
    
    options_text = "\n".join(f"**{letter})** {opt}" for letter, opt in zip(letters, options))
    
    return f"{header}**{question}**\n\n{options_text}"


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


# --- Discord Commands ---

@tree.command(name="ask", description="Ask a question about the squadron documentation")
async def ask_command(interaction: discord.Interaction, question: str):
    """Ask the bot a question grounded in the uploaded PDF."""
    await interaction.response.defer(thinking=True)
    
    enhanced_question = f"{question}\n\n(Answer using ONLY information from the attached PDF documentation. Include page numbers when possible. If the answer isn't in the PDF, say so clearly.)"
    
    answer = await ask_assistant(enhanced_question)
    
    # Discord has a 2000 character limit
    if len(answer) > 1900:
        answer = answer[:1897] + "..."
    
    await interaction.followup.send(answer)


@tree.command(name="quiz_start", description="Start a quiz from the squadron documentation")
async def quiz_start(interaction: discord.Interaction, topic: str = "", questions: int = 6):
    """Start a new quiz session in this channel."""
    if questions < 3 or questions > 10:
        await interaction.response.send_message(
            "❌ Please choose between 3 and 10 questions.",
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
    
    QUIZ_STATE[interaction.channel_id] = {
        "questions": quiz_questions,
        "current_index": 0,
        "scores": {}
    }
    
    first_q = quiz_questions[0]
    topic_text = f" (Topic: {topic})" if topic else ""
    
    await interaction.followup.send(
        f"✈️ **Quiz Started!**{topic_text}\n"
        f"Answer using `/quiz_answer <A|B|C|D>`\n\n" +
        format_mcq(first_q["q"], first_q["options"], 1, len(quiz_questions))
    )


@tree.command(name="quiz_answer", description="Answer the current quiz question")
async def quiz_answer(interaction: discord.Interaction, choice: str):
    """Submit an answer to the current quiz question."""
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
    
    current_idx = state["current_index"]
    question = state["questions"][current_idx]
    correct_answer = question["answer"].strip().upper()
    
    is_correct = (choice == correct_answer)
    
    user_id = str(interaction.user.id)
    if user_id not in state["scores"]:
        state["scores"][user_id] = 0
    
    if is_correct:
        state["scores"][user_id] += 1
    
    if is_correct:
        feedback = f"✅ **Correct!** {interaction.user.mention}"
    else:
        feedback = f"❌ **Incorrect.** The correct answer is **{correct_answer}**."
    
    feedback += f"\n\n💡 **Explanation:** {question['explain']}"
    
    state["current_index"] += 1
    
    if state["current_index"] >= len(state["questions"]):
        scores_sorted = sorted(
            state["scores"].items(),
            key=lambda x: x[1],
            reverse=True
        )
        
        total_questions = len(state["questions"])
        
        leaderboard = "\n".join(
            f"{'🥇' if i == 0 else '🥈' if i == 1 else '🥉' if i == 2 else '📊'} <@{uid}>: **{score}/{total_questions}** ({int(score/total_questions*100)}%)"
            for i, (uid, score) in enumerate(scores_sorted)
        )
        
        QUIZ_STATE.pop(interaction.channel_id, None)
        
        await interaction.response.send_message(
            f"{feedback}\n\n"
            f"🏁 **Quiz Complete!**\n\n"
            f"**Final Scores:**\n{leaderboard}\n\n"
            f"Start a new quiz with `/quiz_start`!"
        )
    else:
        next_q = state["questions"][state["current_index"]]
        next_num = state["current_index"] + 1
        total = len(state["questions"])
        
        await interaction.response.send_message(
            f"{feedback}\n\n" +
            format_mcq(next_q["q"], next_q["options"], next_num, total)
        )


@tree.command(name="quiz_end", description="End the current quiz")
async def quiz_end(interaction: discord.Interaction):
    """Cancel the current quiz in this channel."""
    if interaction.channel_id not in QUIZ_STATE:
        await interaction.response.send_message(
            "❌ No quiz is running in this channel.",
            ephemeral=True
        )
        return
    
    QUIZ_STATE.pop(interaction.channel_id, None)
    await interaction.response.send_message("🛑 Quiz cancelled. Start a new one with `/quiz_start`!")


@tree.command(name="quiz_score", description="Check current quiz scores")
async def quiz_score(interaction: discord.Interaction):
    """Show current scores for the active quiz."""
    state = QUIZ_STATE.get(interaction.channel_id)
    if not state:
        await interaction.response.send_message(
            "❌ No quiz is running in this channel.",
            ephemeral=True
        )
        return
    
    current_q = state["current_index"] + 1
    total_q = len(state["questions"])
    
    if not state["scores"]:
        await interaction.response.send_message(
            f"📊 **Quiz Progress:** Question {current_q}/{total_q}\nNo answers submitted yet!",
            ephemeral=True
        )
        return
    
    scores_sorted = sorted(
        state["scores"].items(),
        key=lambda x: x[1],
        reverse=True
    )
    
    leaderboard = "\n".join(
        f"{'🥇' if i == 0 else '🥈' if i == 1 else '🥉' if i == 2 else '📊'} <@{uid}>: **{score}** points"
        for i, (uid, score) in enumerate(scores_sorted)
    )
    
    await interaction.response.send_message(
        f"📊 **Current Scores** (Question {current_q}/{total_q}):\n{leaderboard}",
        ephemeral=True
    )


@tree.command(name="info", description="Show bot information and stats")
async def info_command(interaction: discord.Interaction):
    """Display bot information."""
    embed = discord.Embed(
        title="✈️ DarkstarAIC",
        description="AI-powered Q&A and quiz bot for DCS squadrons",
        color=discord.Color.blue()
    )
    embed.add_field(name="Model", value="GPT-3.5-turbo", inline=True)
    embed.add_field(name="Servers", value=str(len(client.guilds)), inline=True)
    embed.add_field(name="Version", value="1.0.0", inline=True)
    embed.add_field(
        name="Commands",
        value="• `/ask` - Ask questions\n• `/quiz_start` - Start quiz\n• `/quiz_answer` - Answer question\n• `/quiz_score` - View scores\n• `/quiz_end` - End quiz",
        inline=False
    )
    embed.set_footer(text="Powered by OpenAI Assistants API")
    
    await interaction.response.send_message(embed=embed)


@client.event
async def on_ready():
    """Called when the bot is ready."""
    await tree.sync()
    print(f"✈️ DarkstarAIC is online!")
    print(f"📚 Connected to {len(client.guilds)} server(s)")
    print(f"🤖 Using GPT-3.5-turbo for cost efficiency")


async def start_discord():
    """Start the Discord bot."""
    await client.start(DISCORD_TOKEN)


def main():
    """Main entry point."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    loop.create_task(start_discord())
    
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(api, host="0.0.0.0", port=port, loop="asyncio")


if __name__ == "__main__":
    main()
