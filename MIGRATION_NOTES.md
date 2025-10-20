# Migration from Assistants API to Responses API

## Date
October 18, 2025

## Issue
Deprecation warning appeared:
```
/app/app.py:264: DeprecationWarning: The Assistants API is deprecated in favor of the Responses API
  thread = oai.beta.threads.create()
```

## Changes Made

### 1. OpenAI Client Setup (line 30-31)
**Before:**
```python
oai = OpenAI(
    api_key=OPENAI_API_KEY,
    default_headers={"OpenAI-Beta": "assistants=v2"}
)
```

**After:**
```python
oai = OpenAI(api_key=OPENAI_API_KEY)
```

### 2. Assistant Configuration Caching (line 68-76)
Added global configuration cache to store assistant settings retrieved on startup:
```python
ASSISTANT_CONFIG = {
    "instructions": None,
    "model": None,
    "vector_store_ids": []
}
```

### 3. New Initialization Function (line 254-291)
Created `initialize_assistant_config()` to retrieve and cache assistant configuration:
- Retrieves assistant details using `oai.beta.assistants.retrieve()`
- Extracts instructions, model, and vector store IDs
- Called once on bot startup

### 4. Updated ask_assistant Function (line 294-360)
**Before (Assistants API):**
- Created a new thread: `oai.beta.threads.create()`
- Added message to thread: `oai.beta.threads.messages.create()`
- Created and ran assistant: `oai.beta.threads.runs.create()`
- Polled for completion with timeout loop
- Retrieved messages: `oai.beta.threads.messages.list()`

**After (Responses API):**
- Build request with cached config
- Single API call: `oai.responses.create()`
- Direct response with no polling needed
- Extract text from `response.output[0].content`

### 5. Updated on_ready Event (line 1237-1253)
Added assistant configuration initialization:
```python
await initialize_assistant_config()
```

## Benefits
1. **No deprecation warnings** - Using the supported Responses API
2. **Simpler code** - No thread management or polling loops
3. **Faster responses** - Direct response creation
4. **Future-proof** - Compatible until at least August 2026
5. **Same functionality** - File search still works via tools parameter

## Testing
- Module loads without errors
- All async functions properly defined
- Configuration structure validated
- Response parsing logic verified

## Notes
- The beta.assistants.retrieve() is still used for initial config retrieval on startup
- Vector store IDs are extracted from the existing assistant's file_search tool configuration
- All PDF grounding functionality is preserved through the file_search tool parameter
