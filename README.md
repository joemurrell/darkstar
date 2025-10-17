# DarkstarAIC

**AI-powered Q&A and Quiz Discord Bot for Air Intercept Control and Air Control Communication**

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Discord.py](https://img.shields.io/badge/discord.py-2.4.0-blue.svg)](https://github.com/Rapptz/discord.py)
[![OpenAI](https://img.shields.io/badge/OpenAI-GPT--4.1--mini-green.svg)](https://platform.openai.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-Support-orange.svg)](https://www.buymeacoffee.com/joemurrell)

DarkstarAIC is a Discord bot designed for DCS (Digital Combat Simulator) communities, providing intelligent question-answering and interactive quizzes based on Air Control Communication (ACC) documentation. Powered by OpenAI's GPT-4.1-mini with Assistants API v2, it delivers accurate, PDF-grounded responses to help pilots and controllers master ACC procedures. FOR SIMULATION USE ONLY.

## ✨ Features

- **📚 PDF-Grounded Q&A**: Ask questions about ACC documentation and get accurate answers with page references
- **🎯 Interactive Quizzes**: Test your knowledge with automatically generated multiple-choice quizzes
- **⏱️ Timed Quiz Sessions**: Create time-limited quizzes (1-60 minutes) with customizable question counts
-- **🔍 Smart Topic Diversity**: Quiz questions cover diverse topics from the documentation
- **🤖 GPT-4.1-mini Powered**: Leverages OpenAI's latest model for intelligent, context-aware responses


## 📺 Demo

### Q&A Command
Ask any question about ACC documentation and get instant, accurate answers:
```
/ask What is the proper radio phraseology for requesting takeoff clearance?
```

### Quiz Commands
Start an interactive quiz to test your knowledge:
```
/quiz_start topic:group picture labels questions:5 duration:10
/quiz_end
```

The bot will generate unique questions, track your progress, and provide detailed explanations with page references.

## 📖 Usage

### Commands

- **`/ask <question>`** - Ask a question about ACC documentation
  ```
  /ask What is the standard radio frequency for tower communications?
  ```

- **`/quiz_start [topic] [questions] [duration]`** - Start a quiz session
  - `topic` (optional): Focus on specific topics
  - `questions` (optional): Number of questions (1-10, default: 5)
  - `duration` (optional): Quiz duration in minutes (1-480, default: 15)
  ```
  /quiz_start topic:radio-procedures questions:8 duration:10
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


## 🛠️ Troubleshooting

### Common Issues

**Bot is not responding to commands**
- Verify the bot has proper permissions (Send Messages, Embed Links, Read Message History)
- Check that slash commands are enabled in your server
- Ensure the bot token is valid and the bot is online
- Run `/info` to verify bot is working

**Quiz questions are too similar**
- The bot uses topic diversity to generate varied questions
- Try specifying a topic hint with `/quiz_start topic:your-topic`
- Reduce the number of questions if generation is slow

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

