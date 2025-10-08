# Usage Examples

This document provides step-by-step examples of using DarkstarAIC for squadron SOP management.

## Scenario 1: New Squadron Setup

**Squadron: "Red Devils" DCS Squadron**

### Step 1: Admin Setup
Admin invites the bot and runs setup:

```
User: @Admin
Command: /setup

Bot Response:
✅ Server setup complete!

• Assistant ID: asst_abc123xyz789
• Vector Store ID: vs_def456uvw012

Next steps:
1. Use /upload_document to upload your squadron SOP PDFs
2. Users can then use /ask to ask questions
3. Start quizzes with /quiz_start
```

### Step 2: Upload Documents
Admin uploads squadron SOPs:

```
User: @Admin
Command: /upload_document
Attachment: Red_Devils_SOP_2024.pdf (2.3 MB)

Bot Response:
✅ Document uploaded successfully!

• File: Red_Devils_SOP_2024.pdf
• Size: 2.3 MB
• File ID: file-abc123xyz

The document is now available for Q&A and quizzes!
```

Admin uploads additional documents:

```
User: @Admin
Command: /upload_document
Attachment: Emergency_Procedures.pdf (1.1 MB)

Bot Response:
✅ Document uploaded successfully!

• File: Emergency_Procedures.pdf
• Size: 1.1 MB
• File ID: file-def456uvw

The document is now available for Q&A and quizzes!
```

### Step 3: Verify Setup
Admin checks uploaded documents:

```
User: @Admin
Command: /list_documents

Bot Response:
📚 Uploaded Documents (2)

Documents in this server's knowledge base:

📄 Red_Devils_SOP_2024.pdf
ID: file-abc123xyz
Size: 2.3 MB

📄 Emergency_Procedures.pdf
ID: file-def456uvw
Size: 1.1 MB
```

### Step 4: Squadron Members Use the Bot

#### Example 1: Ask a Question
```
User: @Pilot1
Command: /ask What's the standard formation for Case I recovery?

Bot Response:
According to the Squadron SOP (page 23), the standard formation for Case I recovery is:

1. **Initial Position**: Aircraft enter the break at 800 feet AGL
2. **Spacing**: 15-20 seconds between aircraft
3. **Speed**: 350 knots until the break
4. **Pattern**: Left-hand downwind pattern
5. **Final Turn**: No lower than 180 feet AGL

The pattern should be flown at 600 feet AGL on downwind, descending to 450 feet on base, and intercepting the 3.5° glideslope on final approach.

Reference: Red_Devils_SOP_2024.pdf, page 23
```

#### Example 2: Start a Quiz
```
User: @Pilot2
Command: /quiz_start questions:5 duration:10

Bot Response:
🎯 Quiz Started!

5 questions | 10 minutes

Question 1/5

What is the maximum crosswind component for carrier operations?

A) 15 knots
B) 20 knots
C) 25 knots
D) 30 knots

[Buttons: A  B  C  D]
```

User clicks button "C":

```
Bot Response (ephemeral):
📝 Answer C recorded for question 1!
📊 You've answered 1/5 questions.
⏱️ Time remaining: 9m 45s
```

Bot posts next question automatically:

```
Question 2/5

During a bolter, what is the minimum altitude before turning crosswind?

A) 200 feet
B) 300 feet
C) 400 feet
D) 500 feet

[Buttons: A  B  C  D]
```

After completing all questions:

```
User: @Pilot2
Command: /quiz_end

Bot Response:
🎯 Quiz Results

Final Scores:
1. @Pilot2: 4/5 (80%)
2. @Pilot3: 3/5 (60%)
3. @Pilot1: 5/5 (100%)

Detailed Review:

❌ Question 2: During a bolter, what is the minimum altitude before turning crosswind?
Your answer: B) 300 feet
Correct answer: C) 400 feet
Explanation: According to standard procedures, aircraft must climb to at least 400 feet before turning crosswind to ensure safe separation from the carrier and other traffic. (p.31)

✅ Question 3: [correct answer details...]

Quiz completed! Great job! 🎉
```

## Scenario 2: Updating SOPs

**Situation**: Squadron updates their SOP document to version 2024.1

### Step 1: Remove Old Version
```
User: @Admin
Command: /list_documents

Bot Response:
📚 Uploaded Documents (2)

📄 Red_Devils_SOP_2024.pdf
ID: file-abc123xyz
Size: 2.3 MB

📄 Emergency_Procedures.pdf
ID: file-def456uvw
Size: 1.1 MB
```

```
User: @Admin
Command: /remove_document file-abc123xyz

Bot Response:
✅ Document removed successfully!

• File ID: file-abc123xyz

The document is no longer available for Q&A and quizzes.
```

### Step 2: Upload New Version
```
User: @Admin
Command: /upload_document
Attachment: Red_Devils_SOP_2024.1.pdf (2.5 MB)

Bot Response:
✅ Document uploaded successfully!

• File: Red_Devils_SOP_2024.1.pdf
• Size: 2.5 MB
• File ID: file-ghi789rst

The document is now available for Q&A and quizzes!
```

### Step 3: Announce to Squadron
Admin posts announcement:

```
📢 @everyone SOP Update!

The squadron SOP has been updated to version 2024.1. 

Key changes:
- Updated radio procedures (Chapter 3)
- New formation tactics (Chapter 7)
- Revised emergency procedures (Chapter 9)

Please review the new SOP and test your knowledge with /quiz_start!
```

## Scenario 3: Multi-Squadron Deployment

**Situation**: Two squadrons share the same bot instance

### Squadron A: "Red Devils"
```
Server: Red Devils Discord
Admin: @RedDevil_CO

Commands:
1. /setup → Creates assistant for Red Devils
2. /upload_document → Uploads Red_Devils_SOP.pdf
3. Members use /ask and /quiz_start with their docs
```

### Squadron B: "Blue Angels"  
```
Server: Blue Angels Discord
Admin: @BlueAngel_CO

Commands:
1. /setup → Creates separate assistant for Blue Angels
2. /upload_document → Uploads Blue_Angels_SOP.pdf
3. Members use /ask and /quiz_start with their docs
```

**Result**: Both squadrons have completely isolated knowledge bases. Questions in Red Devils server only access Red Devils documents, and vice versa.

## Scenario 4: Error Handling

### Case 1: User Tries Commands Before Setup
```
User: @NewMember
Command: /ask What is the standard approach speed?

Bot Response:
❌ This server hasn't been set up yet! An admin needs to run /setup first to create an assistant for this server.
```

### Case 2: Non-Admin Tries to Upload
```
User: @RegularMember
Command: /upload_document
[Tries to use command]

Bot Response:
❌ You need Administrator permission to use this command.
```

### Case 3: Invalid File Type
```
User: @Admin
Command: /upload_document
Attachment: sop_document.docx

Bot Response:
❌ Only PDF files are supported. Please upload a PDF document.
```

### Case 4: File Too Large
```
User: @Admin
Command: /upload_document
Attachment: huge_manual.pdf (30 MB)

Bot Response:
❌ File is too large. Maximum size is 25 MB.
```

### Case 5: No Documents Uploaded
```
User: @Member
Command: /quiz_start

Bot Response (after trying to generate):
❌ Couldn't generate a quiz right now. Try:
• Uploading documents first (admin command: /upload_document)
• A more specific topic
• Fewer questions
• Asking again in a moment
```

## Scenario 5: Quiz Session Management

### Multiple Users in Same Quiz
```
[Channel: #training]

User: @Pilot1
Command: /quiz_start questions:5 duration:10

[Quiz starts, questions posted]

@Pilot1 answers question 1: A
@Pilot2 answers question 1: A
@Pilot3 answers question 1: B

[Both see their individual progress]

@Pilot1: "📝 Answer A recorded! You've answered 1/5 questions."
@Pilot2: "📝 Answer A recorded! You've answered 1/5 questions."
@Pilot3: "📝 Answer B recorded! You've answered 1/5 questions."

[After 10 minutes, auto-end shows leaderboard]

Final Scores:
1. @Pilot1: 5/5 (100%)
2. @Pilot2: 4/5 (80%)
3. @Pilot3: 4/5 (80%)
```

### Quiz in Multiple Channels
```
[Channel: #training]
@Pilot1: /quiz_start questions:3 duration:5
→ Quiz runs in #training

[Channel: #general]
@Pilot4: /quiz_start questions:5 duration:10
→ Separate quiz runs in #general

Both quizzes run independently!
```

### Quiz Already Running
```
[Channel: #training]
@Pilot1: /quiz_start questions:5 duration:10
→ Quiz starts

@Pilot2: /quiz_start questions:3 duration:5
Bot Response:
⚠️ There's already a quiz running in this channel! Finish it first or use /quiz_end to cancel.
```

## Scenario 6: Bot Information

```
User: @Anyone
Command: /info

Bot Response:
✈️ DarkstarAIC - Squadron SOP Bot

AI-powered Q&A and quiz bot for DCS Squadron Standard Operating Procedures

Model: GPT-4o-mini
Servers: 12
Version: 2.0.0

Server Status: ✅ Configured

Commands:
• /ask - Ask questions about SOPs
• /quiz_start - Start timed quiz
• /quiz_answer - Answer question
• /quiz_score - View progress
• /quiz_end - End quiz
• /setup - Initialize server (admin)
• /upload_document - Upload SOP PDF (admin)
• /list_documents - List uploaded documents
• /remove_document - Remove document (admin)

Powered by OpenAI Assistants API v2
```

## Tips for Effective Use

### For Admins
1. **Organize documents**: Use clear filenames like "Squadron_SOP_v2.1.pdf"
2. **Version control**: Remove old versions before uploading new ones
3. **Test after upload**: Ask a few questions to verify indexing worked
4. **Communicate changes**: Announce SOP updates to your squadron
5. **Regular review**: Periodically check `/list_documents` and clean up

### For Members
1. **Be specific**: "What is the Case I recovery pattern?" is better than "Tell me about recovery"
2. **Use quizzes regularly**: Practice makes perfect - run quizzes weekly
3. **Review explanations**: Quiz explanations include page numbers for further study
4. **Report issues**: Let admins know if answers seem incorrect
5. **Check page references**: Verify important procedures in the actual SOP

### For Quiz Sessions
1. **Focused topics**: Use `/quiz_start topic:emergency-procedures` for targeted training
2. **Reasonable length**: 5-10 questions works well for most sessions
3. **Adequate time**: Allow 1-2 minutes per question minimum
4. **Team training**: Encourage multiple members to participate simultaneously
5. **Follow-up**: Discuss missed questions as a group after the quiz
