# ✈️ DarkstarAIC

**AI-powered Q&A and Quiz Discord Bot for Air Control Communication**

DarkstarAIC is a Discord bot designed for DCS (Digital Combat Simulator) communities, providing intelligent question-answering and interactive quizzes based on Air Control Communication (ACC) documentation. Powered by OpenAI's GPT-4.1-mini with Assistants API v2, it delivers accurate, PDF-grounded responses to help pilots and controllers master ACC procedures.

## ✨ Features

- **📚 PDF-Grounded Q&A**: Ask questions about ACC documentation and get accurate answers with page references
- **🎯 Interactive Quizzes**: Test your knowledge with automatically generated multiple-choice quizzes
- **⏱️ Timed Quiz Sessions**: Create time-limited quizzes (1-60 minutes) with customizable question counts
- **📊 Progress Tracking**: Monitor your quiz performance and track answered questions
- **🔍 Smart Topic Diversity**: Quiz questions cover diverse topics from the documentation
- **🤖 GPT-4.1-mini Powered**: Leverages OpenAI's latest model for intelligent, context-aware responses
- **🛡️ Permission Management**: Ensures bot has necessary permissions before responding

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- Discord Bot Token
- OpenAI API Key
- OpenAI Assistant ID (with ACC documentation uploaded)

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/joemurrell/darkstar.git
   cd darkstar
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up environment variables**
   ```bash
   export DISCORD_TOKEN="your_discord_bot_token"
   export OPENAI_API_KEY="your_openai_api_key"
   export ASSISTANT_ID="your_openai_assistant_id"
   ```

4. **Run the bot**
   ```bash
   python app.py
   ```

### Docker Deployment

```bash
docker build -t darkstar-aic .
docker run -e DISCORD_TOKEN="your_token" \
           -e OPENAI_API_KEY="your_key" \
           -e ASSISTANT_ID="your_assistant_id" \
           darkstar-aic
```

### Railway Deployment

This bot is configured for easy deployment on [Railway](https://railway.app/):

1. Fork this repository
2. Create a new Railway project from your fork
3. Add the required environment variables
4. Railway will automatically build and deploy using the included `railway.json` and `Dockerfile`

## 📖 Usage

### Commands

- **`/ask <question>`** - Ask a question about ACC documentation
  ```
  /ask What is the standard radio frequency for tower communications?
  ```

- **`/quiz_start [topic] [questions] [duration]`** - Start a quiz session
  - `topic` (optional): Focus on specific topics
  - `questions` (optional): Number of questions (1-10, default: 6)
  - `duration` (optional): Quiz duration in minutes (1-60, default: 5)
  ```
  /quiz_start topic:radio-procedures questions:8 duration:10
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

- **`/info`** - Display bot information and statistics
  ```
  /info
  ```

## 🔧 Configuration

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `DISCORD_TOKEN` | Your Discord bot token from the [Discord Developer Portal](https://discord.com/developers/applications) | Yes |
| `OPENAI_API_KEY` | Your OpenAI API key from [OpenAI Platform](https://platform.openai.com/api-keys) | Yes |
| `ASSISTANT_ID` | OpenAI Assistant ID with ACC documentation uploaded | Yes |

### Setting Up OpenAI Assistant

1. Go to [OpenAI Platform](https://platform.openai.com/)
2. Navigate to Assistants
3. Create a new Assistant
4. Upload your ACC documentation PDF(s)
5. Configure the assistant to use GPT-4.1-mini
6. Enable File Search for PDF grounding
7. Copy the Assistant ID

### Discord Bot Setup

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Create a new application
3. Add a bot user
4. Enable required intents:
   - Message Content Intent
   - Server Members Intent (optional)
5. Generate bot token
6. Invite bot to your server with required permissions:
   - Send Messages
   - Embed Links
   - Read Message History

## 🏗️ Architecture

- **Framework**: Discord.py 2.4.0
- **AI Model**: OpenAI GPT-4.1-mini via Assistants API v2
- **Language**: Python 3.11
- **Deployment**: Docker-ready, Railway-configured
- **Logging**: Structured logging for Railway compatibility

## 📝 Development

### Project Structure

```
darkstar/
├── app.py              # Main bot application
├── requirements.txt    # Python dependencies
├── Dockerfile         # Docker configuration
├── railway.json       # Railway deployment config
├── LICENSE           # MIT License
└── README.md         # This file
```

### Key Components

- **Question Answering**: Uses OpenAI Assistants API with file search for accurate, grounded responses
- **Quiz Generation**: Dynamically creates diverse multiple-choice questions from documentation
- **Session Management**: Tracks quiz sessions per Discord channel
- **Fuzzy Matching**: Accepts approximate answers using Levenshtein distance

## 🤝 Contributing

Contributions are welcome! Please feel free to submit issues, fork the repository, and create pull requests.

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 💖 Support

If you find this bot useful, consider supporting the development:

[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-joemurrell-yellow.svg?style=flat&logo=buy-me-a-coffee)](https://www.buymeacoffee.com/joemurrell)

## 🙏 Acknowledgments

- Built for the DCS community
- Powered by OpenAI's GPT-4.1-mini
- Uses Discord.py for Discord integration

## 📊 Version

Current version: **1.0.2**

---

**Made with ✈️ for DCS Air Control Communication training**
