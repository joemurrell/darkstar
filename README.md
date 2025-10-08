# DarkstarAIC

**AI-powered Multi-Server Q&A and Quiz Discord Bot for DCS Squadron SOPs**

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Discord.py](https://img.shields.io/badge/discord.py-2.4.0-blue.svg)](https://github.com/Rapptz/discord.py)
[![OpenAI](https://img.shields.io/badge/OpenAI-GPT--4o--mini-green.svg)](https://platform.openai.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-Support-orange.svg)](https://www.buymeacoffee.com/joemurrell)

DarkstarAIC is a Discord bot designed for DCS (Digital Combat Simulator) squadrons, providing intelligent question-answering and interactive quizzes based on squadron-specific Standard Operating Procedures (SOPs). Powered by OpenAI's GPT-4o-mini with Assistants API v2, it delivers accurate, PDF-grounded responses to help squadron members master their procedures. **NEW**: Supports multiple servers with per-server document uploads! FOR SIMULATION USE ONLY.

## ✨ Features

- **📚 PDF-Grounded Q&A**: Ask questions about squadron SOPs and get accurate answers with page references
- **🎯 Interactive Quizzes**: Test your knowledge with automatically generated multiple-choice quizzes
- **⏱️ Timed Quiz Sessions**: Create time-limited quizzes (1-60 minutes) with customizable question counts
- **🔍 Smart Topic Diversity**: Quiz questions cover diverse topics from the documentation
- **🏢 Multi-Server Support**: Each Discord server can have its own assistant and document library
- **📤 Document Upload**: Server admins can upload squadron-specific SOP PDFs
- **🔐 Admin Controls**: Setup and document management restricted to server administrators
- **🤖 GPT-4o-mini Powered**: Leverages OpenAI's latest model for intelligent, context-aware responses


## 📺 Demo

### Setup and Document Upload (Admin)
Initialize your server and upload squadron SOPs:
```
/setup
/upload_document [attach PDF file]
/list_documents
```

### Q&A Command
Ask any question about your squadron's SOPs:
```
/ask What is the proper radio phraseology for requesting takeoff clearance?
```

### Quiz Commands
Start an interactive quiz to test squadron knowledge:
```
/quiz_start topic:emergency-procedures questions:5 duration:10
/quiz_end
```

The bot will generate unique questions from your uploaded SOPs, track progress, and provide detailed explanations with page references.

## 📖 Usage

### Setup (Admin Only)

Before using the bot, a server administrator must initialize it:

1. **Initialize the server:**
   ```
   /setup
   ```
   This creates a dedicated OpenAI assistant and vector store for your server.

2. **Upload SOP documents:**
   ```
   /upload_document
   ```
   Attach a PDF file containing your squadron's SOPs. You can upload multiple documents.

3. **Verify uploads:**
   ```
   /list_documents
   ```
   View all uploaded documents and their file IDs.

### Commands

**Admin Commands:**

- **`/setup`** - Initialize the bot for your server (creates assistant and vector store)
  ```
  /setup
  ```

- **`/upload_document [file]`** - Upload a SOP PDF document
  ```
  /upload_document [attach PDF file]
  ```

- **`/remove_document <file_id>`** - Remove a document from the knowledge base
  ```
  /remove_document file-abc123xyz
  ```

**User Commands:**

- **`/ask <question>`** - Ask a question about squadron SOPs
  ```
  /ask What is the standard radio frequency for tower communications?
  ```

- **`/quiz_start [topic] [questions] [duration]`** - Start a quiz session
  - `topic` (optional): Focus on specific topics
  - `questions` (optional): Number of questions (1-10, default: 6)
  - `duration` (optional): Quiz duration in minutes (1-60, default: 5)
  ```
  /quiz_start topic:emergency-procedures questions:8 duration:10
  ```

- **`/quiz_answer <answer>`** - Answer the current quiz question
  ```
  /quiz_answer A
  ```

- **`/quiz_score`** - View your current quiz progress
  ```
  /quiz_score
  ```

- **`/quiz_end`** - End the current quiz and view final results
  ```
  /quiz_end
  ```

- **`/list_documents`** - View all uploaded documents
  ```
  /list_documents
  ```

- **`/info`** - Display bot information and statistics
  ```
  /info
  ```


## ⚙️ Configuration

DarkstarAIC supports two deployment modes:

### Multi-Server Mode (Recommended)

Each Discord server gets its own assistant and document library. This is the default mode.

**Environment Variables:**
- `DISCORD_TOKEN` - Your Discord bot token (required)
- `OPENAI_API_KEY` - Your OpenAI API key (required)
- `ASSISTANT_ID` - Leave unset for multi-server mode

**Setup:**
1. Admin runs `/setup` in each server
2. Bot creates a dedicated assistant and vector store
3. Admin uploads server-specific SOP documents with `/upload_document`

### Single-Server Mode (Legacy)

Uses one global assistant for all servers. Useful if all servers share the same documentation.

**Environment Variables:**
- `DISCORD_TOKEN` - Your Discord bot token (required)
- `OPENAI_API_KEY` - Your OpenAI API key (required)
- `ASSISTANT_ID` - Your pre-configured OpenAI assistant ID

**Setup:**
1. Pre-configure an OpenAI assistant with documents
2. Set `ASSISTANT_ID` environment variable
3. Bot uses this assistant for all servers


## 🛠️ Troubleshooting

### Common Issues

**"This server hasn't been set up yet" error**
- An admin needs to run `/setup` to initialize the bot for your server
- This creates a dedicated assistant and vector store for your squadron

**Bot is not responding to commands**
- Verify the bot has proper permissions (Send Messages, Embed Links, Read Message History)
- Check that slash commands are enabled in your server
- Ensure the bot token is valid and the bot is online
- Run `/info` to verify bot is working

**Document upload fails**
- Ensure file is a PDF and under 25 MB
- Check that you have administrator permissions
- Verify your OpenAI API key has sufficient credits
- Run `/setup` first if you haven't already

**No answers or quiz questions available**
- Make sure documents have been uploaded with `/upload_document`
- Check `/list_documents` to verify documents are in the system
- Wait a few moments after uploading for indexing to complete

**Quiz questions are too similar**
- The bot uses topic diversity to generate varied questions
- Try specifying a topic hint with `/quiz_start topic:your-topic`
- Reduce the number of questions if generation is slow
- Ensure you have multiple documents uploaded covering different topics

**"Permission denied" errors**
- Check bot role permissions in Discord server settings
- Ensure bot role is above other roles in the hierarchy
- Grant "Use Application Commands" permission

**Quiz timing out or not working**
- Only one quiz can run per Discord channel at a time
- End the current quiz with `/quiz_end` before starting a new one
- Check that quiz duration is between 1-60 minutes

For more help, please [open an issue](https://github.com/joemurrell/darkstar/issues) on GitHub.

## 🤝 Contributing

Contributions are welcome! Please feel free to submit issues, fork the repository, and create pull requests.

## 💖 Support

If you find this bot useful, consider supporting the development:

[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-joemurrell-yellow.svg?style=flat&logo=buy-me-a-coffee)](https://www.buymeacoffee.com/joemurrell)


---

