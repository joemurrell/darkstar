# Quiz Diversity Enhancement - Quick Start Guide

## What Changed?

The bot now generates **diverse, non-repetitive quiz questions** automatically.

## For Users: Nothing Changed!

Continue using the bot exactly as before:
```
/quiz_start topic:"emergency procedures" questions:6 duration:5
```

The diversity improvements work automatically in the background.

## For Developers: Quick Reference

### Run Tests
```bash
pip install -r requirements.txt
python run_tests.py
```
**Expected**: All 14 tests pass ✓

### See Demo
```bash
python demo_diversity.py
```
**Shows**: How deduplication removes duplicate questions

### Check Logs
```bash
tail -f logs/ai_replies.log
```
**Contains**: All assistant responses and deduplication results

## Key Features

✅ **Diversity Enforcement**: Questions have unique topics
✅ **Deduplication**: Removes similar questions automatically  
✅ **Regeneration**: Retries if duplicates found (max 3 attempts)
✅ **Logging**: All responses logged for debugging
✅ **Tests**: 14 comprehensive tests (all passing)

## What Was Added?

### New Functions (in app.py)
- `extract_topic_from_question()` - Extract/compute topic tags
- `extract_keywords()` - Extract content keywords
- `are_questions_similar()` - Detect duplicate questions
- `deduplicate_questions()` - Remove duplicates

### Enhanced Functions
- `ask_assistant()` - Now supports temperature and frequency_penalty
- `generate_quiz()` - Now deduplicates and regenerates
- `shuffle_quiz_options()` - Preserves topic and page fields

### New Files
- `tests/test_generate_quiz.py` - 14 comprehensive tests
- `run_tests.py` - Test runner
- `demo_diversity.py` - Interactive demonstration
- Documentation files (QUIZ_DIVERSITY_CHANGES.md, etc.)

## How It Works

```
1. Generate questions with diversity prompt
   ↓
2. Parse and validate responses
   ↓
3. Deduplicate using 3-method similarity detection:
   - Exact topic match
   - Fuzzy text similarity (>85%)
   - Keyword overlap (>40%)
   ↓
4. If unique count < requested:
   - Regenerate with topic exclusion
   - Repeat up to 3 times
   ↓
5. Return unique questions
   ↓
6. Log everything to logs/ai_replies.log
```

## Example Before/After

### BEFORE (Problem)
```json
[
  {"q": "What is PUSHING the throttle?", "topic": "pushing"},
  {"q": "How to perform PUSHING?", "topic": "pushing"},  // Duplicate!
  {"q": "FUMBLE recovery procedure?", "topic": "fumble"},
  {"q": "Steps for FUMBLE situation?", "topic": "fumble"}  // Duplicate!
]
```

### AFTER (Solution)
```json
[
  {"q": "What is throttle operation?", "topic": "throttle-operation"},
  {"q": "Emergency recovery procedure?", "topic": "emergency-recovery"},
  {"q": "Fuel capacity of main tank?", "topic": "fuel-capacity"},
  {"q": "Maximum altitude for combat?", "topic": "altitude-limits"}
]
```

## Troubleshooting

### "Module not found" error
```bash
pip install -r requirements.txt
```

### Tests failing
```bash
# Ensure environment variables are set (run_tests.py does this automatically)
DISCORD_TOKEN=test OPENAI_API_KEY=test ASSISTANT_ID=test python -m unittest
```

### Want to see deduplication in action?
```bash
python demo_diversity.py
```

## Documentation

- **IMPLEMENTATION_SUMMARY.md** - Complete technical overview
- **QUIZ_DIVERSITY_CHANGES.md** - Detailed changes and implementation
- **BEFORE_AFTER_COMPARISON.md** - Side-by-side comparison
- **QUICK_START.md** - This file

## Support

Check logs for debugging:
```bash
tail -f logs/ai_replies.log
```

Look for:
- "After deduplication: X unique out of Y"
- "Regeneration attempt N/3"
- "Final quiz: X unique questions"

## Status

✅ **Production Ready**  
✅ **All Tests Passing (14/14)**  
✅ **Fully Documented**  
✅ **Backward Compatible**  

No action required - just deploy and use!
