# Multi-Server Setup Guide

This guide explains how to set up and use DarkstarAIC in multi-server mode for squadron-specific SOPs.

## Overview

DarkstarAIC now supports **per-server assistants**, allowing each Discord server to have its own:
- Dedicated OpenAI assistant
- Private document library (vector store)
- Squadron-specific SOP documents

This means multiple squadrons can use the same bot instance while keeping their documents and training data separate.

## Quick Start

### For Server Administrators

1. **Initialize your server:**
   ```
   /setup
   ```
   This creates a dedicated assistant and vector store for your squadron.

2. **Upload your squadron's SOPs:**
   ```
   /upload_document
   ```
   Click the command and attach a PDF file. You can upload multiple documents.

3. **Verify uploads:**
   ```
   /list_documents
   ```
   See all documents in your server's knowledge base.

4. **Let your squadron know they can start using the bot!**

### For Squadron Members

Once an admin has set up the server:

- **Ask questions:**
  ```
  /ask What's the standard approach pattern for Case I recovery?
  ```

- **Start a quiz:**
  ```
  /quiz_start questions:5 duration:10
  ```

- **Check your progress:**
  ```
  /quiz_score
  ```

## Deployment Modes

### Multi-Server Mode (Default)

**When to use:** You want to support multiple squadrons with different SOPs.

**Configuration:**
- Set `DISCORD_TOKEN` and `OPENAI_API_KEY`
- Do NOT set `ASSISTANT_ID`

**How it works:**
- Each server administrator runs `/setup`
- Bot creates a unique assistant for each server
- Admins upload server-specific documents
- Documents are isolated per server

**Pros:**
- Complete isolation between servers
- Each squadron has their own knowledge base
- Admins control their own content
- Scales to unlimited servers

**Cons:**
- Each server requires setup
- Uses more OpenAI resources (one assistant per server)
- In-memory storage means assistants are recreated if bot restarts (in production, use a database)

### Single-Server Mode (Legacy)

**When to use:** All servers should use the same documentation, or you're only running on one server.

**Configuration:**
- Set `DISCORD_TOKEN`, `OPENAI_API_KEY`, and `ASSISTANT_ID`
- Pre-configure your assistant with documents in OpenAI platform

**How it works:**
- Bot uses the same assistant for all servers
- No per-server setup needed
- Documents shared across all servers

**Pros:**
- Simple configuration
- Single assistant to manage
- No setup command needed

**Cons:**
- All servers see the same documents
- Can't customize per squadron
- Less suitable for multi-squadron deployments

## Document Management

### Uploading Documents

Requirements:
- Must be a server administrator
- File must be PDF format
- Maximum file size: 25 MB

Steps:
1. Run `/upload_document`
2. Attach your PDF file
3. Wait for confirmation (usually a few seconds)

The bot will:
- Upload the file to OpenAI
- Add it to your server's vector store
- Index the content for Q&A and quizzes

### Listing Documents

Anyone can view the document list:
```
/list_documents
```

This shows:
- Document filename
- File ID
- File size
- Total document count

### Removing Documents

Administrators can remove documents:
```
/remove_document file-abc123xyz
```

Get the file ID from `/list_documents`.

## Architecture Details

### Data Storage

**Current implementation (v2.0.0):**
- Guild assistants stored in `GUILD_ASSISTANTS` dictionary (in-memory)
- Data is lost when bot restarts
- Suitable for testing and development

**Recommended for production:**
- Store guild assistant mappings in a database (PostgreSQL, MongoDB, etc.)
- Load mappings on bot startup
- Persist across restarts

### OpenAI Resources

For each server with `/setup`:
- 1 OpenAI Assistant (cost: free, just API usage)
- 1 Vector Store (cost: $0.10/GB/day)
- N uploaded files (cost: included in vector store)

Example: 10 servers with 50 MB each = ~0.5 GB = $0.05/day

### API Usage

- `/ask` - Creates a thread and runs the assistant (~1-2 API calls)
- `/quiz_start` - Generates questions (~2-4 API calls depending on settings)
- Document upload - Processes and indexes the PDF

## Best Practices

### For Bot Operators

1. **Monitor OpenAI costs** - Each server adds resources
2. **Set up monitoring** - Track which servers are active
3. **Implement database storage** - Don't rely on in-memory state in production
4. **Rate limiting** - Consider adding rate limits for document uploads
5. **Backup strategy** - Export assistant IDs and vector store IDs periodically

### For Server Administrators

1. **Organize documents** - Name PDFs clearly (e.g., "Squadron_SOP_v2.1.pdf")
2. **Update regularly** - Remove old versions and upload new ones
3. **Test after upload** - Ask a few questions to verify the content is indexed
4. **Communicate with members** - Let them know when SOPs are updated
5. **Keep documents focused** - Upload only relevant SOP documents

### For Squadron Members

1. **Be specific** - Ask clear, detailed questions
2. **Use topic filters** - In quizzes, focus on specific topics (e.g., `/quiz_start topic:emergency-procedures`)
3. **Check page references** - Answers include page numbers for verification
4. **Report issues** - Let admins know if answers seem incorrect

## Migration Guide

### From v1.0 (Single Assistant) to v2.0 (Multi-Server)

If you were using the old version with a single `ASSISTANT_ID`:

**Option 1: Keep single-server mode**
- No changes needed
- Continue setting `ASSISTANT_ID`
- All servers share documents

**Option 2: Migrate to multi-server mode**
1. Remove `ASSISTANT_ID` from environment
2. Restart bot
3. Run `/setup` in each server
4. Upload documents to each server
5. Old assistant can be deleted from OpenAI if no longer needed

## Troubleshooting

### "This server hasn't been set up yet"

**Problem:** Commands return error saying server not configured.

**Solution:** An administrator needs to run `/setup` first.

### Setup fails with API error

**Problem:** `/setup` command returns an error.

**Possible causes:**
- Invalid or expired OpenAI API key
- Insufficient API credits
- Rate limit exceeded

**Solution:**
- Check API key in environment variables
- Verify OpenAI account has credits
- Wait a few minutes and try again

### Documents not showing up in answers

**Problem:** Questions return "not in the documents" even though you uploaded them.

**Solution:**
- Wait 1-2 minutes after upload for indexing
- Verify document was uploaded with `/list_documents`
- Try asking more specific questions
- Check if the information is actually in the uploaded PDFs

### "Permission denied" when uploading

**Problem:** Can't use `/upload_document` even though you're an admin.

**Solution:**
- Verify you have Administrator permission in server settings
- Check bot has necessary permissions
- Try running `/setup` first if you haven't

## Example Workflows

### New Squadron Setup

1. Admin invites bot to server
2. Admin runs `/setup`
3. Admin uploads squadron SOPs:
   - `squadron_general_procedures.pdf`
   - `squadron_brevity.pdf`
   - `squadron_tactics.pdf`
4. Admin announces in squadron channel
5. Members start using `/ask` and `/quiz_start`

### Updating SOPs

1. Squadron updates SOP document
2. Admin runs `/list_documents` to find old version
3. Admin runs `/remove_document file-old123` to remove old version
4. Admin runs `/upload_document` to upload new version
5. Admin announces update to members

### Multi-Squadron Deployment

1. Bot operator deploys bot (remove `ASSISTANT_ID`)
2. Squadron A admin runs `/setup` in their server
3. Squadron B admin runs `/setup` in their server
4. Each uploads their own documents
5. Squadrons operate independently with isolated knowledge bases

## Support

For issues or questions:
- GitHub Issues: https://github.com/joemurrell/darkstar/issues
- Check the main README.md for additional troubleshooting

## Future Enhancements

Potential improvements for future versions:
- Database storage for persistence
- Document versioning
- Usage analytics per server
- Document sharing between servers
- Bulk document operations
- Document categories/tags
- Search within documents
- Scheduled quiz sessions
