# Quiz Diversity Enhancements

## Overview
This document describes the changes made to resolve repetitive quiz questions by enforcing diversity, adding deduplication/regeneration, and logging assistant responses.

## Changes Made

### 1. Enhanced Prompt with Diversity Requirements
The quiz generation prompt now includes:
- Explicit instructions to avoid repeating keywords (e.g., "PUSHING", "FUMBLE")
- Requirement for each question to cover a different topic/concept
- New fields: `topic` (hyphenated tag) and `page` (page number)
- Example structure showing the new format

### 2. Assistant API Parameters
Updated `ask_assistant()` to support:
- `temperature` parameter (default: 0.7 for quiz generation)
- `frequency_penalty` parameter (default: 0.3 for quiz generation)
- These parameters encourage more diverse responses

### 3. Logging Infrastructure
- Created `logs/` directory for storing assistant responses
- Configured Python logging to write to `logs/ai_replies.log`
- Logs include:
  - Timestamp and context (topic_hint, num_questions)
  - Raw assistant replies (truncated to 1000 chars)
  - Deduplication results
  - Topic assignments
  - Final quiz composition

### 4. Deduplication Helper Functions
Added helper functions in `app.py`:

**`extract_topic_from_question(question_dict)`**
- Extracts topic from provided `topic` field or computes from question text
- Uses keyword extraction and stopword filtering
- Returns normalized topic string

**`extract_keywords(text, top_n=5)`**
- Extracts top N content keywords from text
- Filters out stopwords
- Returns set of keywords

**`are_questions_similar(q1, q2, topic1, topic2)`**
- Determines if two questions are too similar
- Considers duplicates if:
  - Topics match exactly
  - Text similarity > 85% (fuzzy ratio)
  - Share > 40% of top 5 keywords

**`deduplicate_questions(questions)`**
- Removes duplicate/similar questions from a list
- Returns tuple of (unique_questions, used_topics)

### 5. Regeneration Loop
The `generate_quiz()` function now:
1. Makes initial request with diversity prompt
2. Deduplicates returned questions
3. If unique count < requested count:
   - Requests replacement questions (up to 3 attempts)
   - Excludes already-used topics in regeneration prompt
   - Increases temperature (0.8) and frequency_penalty (0.4) for more diversity
4. Logs all attempts and results
5. Returns requested number of unique questions or fewer with clear logging

### 6. Updated shuffle_quiz_options()
Now preserves optional `topic` and `page` fields when shuffling answer options.

### 7. Test Suite
Created `tests/test_generate_quiz.py` with:
- Unit tests for topic extraction
- Unit tests for keyword extraction
- Unit tests for similarity detection
- Unit tests for deduplication
- Integration tests with mocked assistant responses demonstrating:
  - Successful generation without regeneration
  - Regeneration triggered by duplicates
  - Max retry limiting

### 8. Dependencies
Added to `requirements.txt`:
- `fuzzywuzzy==0.18.0` - for fuzzy string matching
- `python-Levenshtein==0.25.1` - for efficient string comparisons

## Testing

Run tests with:
```bash
python run_tests.py
```

All 14 tests should pass, demonstrating:
- Topic extraction works correctly
- Keyword extraction filters stopwords
- Similar questions are detected
- Deduplication removes duplicates
- Regeneration loop works with mocked responses

## Usage

No changes to the bot's external interface. Users continue to use:
```
/quiz_start topic:"emergency procedures" questions:6 duration:5
```

The bot will now:
1. Generate diverse questions with unique topics
2. Automatically deduplicate similar questions
3. Regenerate if needed to meet the requested count
4. Log all interactions for debugging

## Logging Example

Check `logs/ai_replies.log` for entries like:
```
2025-10-04 20:23:44,001 - app - INFO - Generating quiz: topic_hint='emergency procedures', num_questions=6
2025-10-04 20:23:44,001 - app - INFO - Assistant raw reply (first 1000 chars): [{"q": "What is...", ...}]
2025-10-04 20:23:44,001 - app - INFO - After deduplication: 4 unique out of 6 initial questions
2025-10-04 20:23:44,001 - app - INFO - Used topics: ['throttle-operation', 'emergency-recovery', ...]
2025-10-04 20:23:44,001 - app - INFO - Regeneration attempt 1/3: need 2 more questions
2025-10-04 20:23:44,002 - app - INFO - Final quiz: 6 unique questions (requested: 6)
```

## Acceptance Criteria Met

✅ For repeated runs, returned quizzes should not have more than one question sharing the same topic tag or dominant keyword
✅ Raw assistant replies are logged for debugging
✅ If the assistant cannot produce distinct topics after bounded retries, generate_quiz returns a clear message or fewer questions
✅ Unit tests demonstrating deduplication and replacement logic (with mocked responses) are included

## Files Changed

- `app.py` - Main logic updates
- `requirements.txt` - Added dependencies
- `.gitignore` - Excluded logs directory
- `tests/test_generate_quiz.py` - New test suite
- `tests/__init__.py` - Tests package marker
- `run_tests.py` - Test runner with environment setup
- `QUIZ_DIVERSITY_CHANGES.md` - This documentation

## Notes

- The regeneration loop is bounded to a maximum of 3 attempts to avoid infinite loops
- Logging writes to both file and console for easy monitoring
- The logs directory is excluded from git via .gitignore
- Temperature and frequency_penalty can be adjusted if needed for different diversity levels
