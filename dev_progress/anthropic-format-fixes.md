# Anthropic Provider Format Fixes

**Date:** 2025-12-31
**Purpose:** Document all format conversion issues discovered and fixed for Anthropic provider

---

## Problems Discovered

When integrating the Anthropic provider, we encountered three critical format mismatches between OpenAI's API format (which clio uses internally) and Anthropic's native format.

---

## Issue 1: Tool Definitions Format

**Error:**
```
Error code: 400 - tools.0: Input tag 'function' found using 'type' does not match any of the expected tags
```

**Root Cause:**
Agent was passing tool definitions in OpenAI format:
```json
[{
  "type": "function",
  "function": {
    "name": "web_search",
    "description": "Search the web",
    "parameters": {
      "type": "object",
      "properties": {...}
    }
  }
}]
```

**Anthropic Expects:**
```json
[{
  "name": "web_search",
  "description": "Search the web",
  "input_schema": {
    "type": "object",
    "properties": {...}
  }
}]
```

**Fix:**
Created `_convert_tools_to_anthropic()` method in `anthropic.py` (lines 216-241) that:
1. Extracts the `function` object from OpenAI's wrapper
2. Renames `parameters` → `input_schema`
3. Removes the `type: "function"` wrapper

---

## Issue 2: Tool Result Messages Format

**Error:**
```
Error code: 400 - Unexpected role 'tool'. Allowed roles are 'user' or 'assistant'
```

**Root Cause:**
Agent was passing tool results in OpenAI format:
```json
{
  "role": "tool",
  "tool_call_id": "call_123",
  "content": "Search results..."
}
```

**Anthropic Expects:**
```json
{
  "role": "user",
  "content": [
    {
      "type": "tool_result",
      "tool_use_id": "call_123",
      "content": "Search results..."
    }
  ]
}
```

**Fix:**
Added conversion logic in `_convert_messages_to_anthropic()` (lines 164-175) that:
1. Changes `role: "tool"` → `role: "user"`
2. Wraps content in a content block array
3. Renames `tool_call_id` → `tool_use_id`
4. Adds `type: "tool_result"`

---

## Issue 3: Assistant Messages with Tool Calls

**Error:**
```
Error code: 400 - messages.3.tool_calls: Extra inputs are not permitted
```

**Root Cause:**
When reconstructing conversation history, assistant messages were in OpenAI format:
```json
{
  "role": "assistant",
  "content": "Let me search for that.",
  "tool_calls": [
    {
      "id": "call_123",
      "type": "function",
      "function": {
        "name": "web_search",
        "arguments": "{\"query\": \"zebras\"}"
      }
    }
  ]
}
```

**Anthropic Expects:**
```json
{
  "role": "assistant",
  "content": [
    {
      "type": "text",
      "text": "Let me search for that."
    },
    {
      "type": "tool_use",
      "id": "call_123",
      "name": "web_search",
      "input": {"query": "zebras"}
    }
  ]
}
```

**Fix:**
Added conversion logic in `_convert_messages_to_anthropic()` (lines 177-208) that:
1. Converts `content` from string → array of content blocks
2. Adds `type: "text"` block for text content
3. Converts `tool_calls` array → `tool_use` content blocks
4. Parses JSON `arguments` string → `input` object
5. Removes the `tool_calls` field entirely

---

## Complete Solution: Message Converter

Created comprehensive `_convert_messages_to_anthropic()` method (lines 148-214) that handles ALL message conversions:

```python
def _convert_messages_to_anthropic(self, messages: List[Message]) -> tuple[Optional[str], List[Dict[str, Any]]]:
    """Convert OpenAI-format messages to Anthropic format.

    Returns:
        Tuple of (system_message, anthropic_messages)
    """
```

**Handles:**
1. **System messages** - Extracted and returned separately (Anthropic uses `system` parameter)
2. **Tool result messages** - Converted from `role: "tool"` to `role: "user"` with content blocks
3. **Assistant messages with tool calls** - Converted from flat structure to content block array
4. **Regular messages** - Passed through unchanged

**Used in:**
- `chat()` method (line 43)
- `stream_chat()` method (line 81)

---

## Reference: Official Anthropic Documentation

**Source:** https://platform.claude.com/docs/en/api/messages

### Content Block Types

1. **text blocks:**
   ```json
   {"type": "text", "text": "content"}
   ```

2. **tool_use blocks:**
   ```json
   {
     "type": "tool_use",
     "id": "unique_id",
     "name": "tool_name",
     "input": {}
   }
   ```

3. **tool_result blocks:**
   ```json
   {
     "type": "tool_result",
     "tool_use_id": "matching_id",
     "content": "result"
   }
   ```

### Complete Tool Calling Cycle

**1. User sends message with tools available:**
```json
{
  "model": "claude-sonnet-4-5-20250929",
  "max_tokens": 1024,
  "tools": [
    {
      "name": "web_search",
      "description": "Search the web",
      "input_schema": {
        "type": "object",
        "properties": {
          "query": {"type": "string"}
        },
        "required": ["query"]
      }
    }
  ],
  "messages": [
    {"role": "user", "content": "Search for zebra facts"}
  ]
}
```

**2. Claude responds with tool_use:**
```json
{
  "role": "assistant",
  "content": [
    {
      "type": "tool_use",
      "id": "toolu_01ABC",
      "name": "web_search",
      "input": {"query": "zebra facts"}
    }
  ],
  "stop_reason": "tool_use"
}
```

**3. User sends tool result:**
```json
{
  "messages": [
    {"role": "user", "content": "Search for zebra facts"},
    {
      "role": "assistant",
      "content": [
        {
          "type": "tool_use",
          "id": "toolu_01ABC",
          "name": "web_search",
          "input": {"query": "zebra facts"}
        }
      ]
    },
    {
      "role": "user",
      "content": [
        {
          "type": "tool_result",
          "tool_use_id": "toolu_01ABC",
          "content": "Zebras are African equids..."
        }
      ]
    }
  ]
}
```

**4. Claude responds with final answer:**
```json
{
  "role": "assistant",
  "content": [
    {
      "type": "text",
      "text": "Here are 5 facts about zebras..."
    }
  ],
  "stop_reason": "end_turn"
}
```

---

## Key Differences Summary

| Aspect | OpenAI Format | Anthropic Format |
|--------|---------------|------------------|
| Tool definitions | `type: "function"`, `function` object, `parameters` | No wrapper, direct fields, `input_schema` |
| Tool result role | `"tool"` | `"user"` |
| Tool result structure | Flat with `tool_call_id` | Content blocks with `tool_use_id` |
| Assistant with tools | `content` string + `tool_calls` array | `content` array with mixed text/tool_use blocks |
| System messages | In messages array | Separate `system` parameter |
| Argument format | JSON string in `arguments` | Object in `input` |

---

## Testing Status

- [x] Simple text responses
- [x] Tool definitions accepted
- [ ] Tool execution and result handling (in progress)
- [ ] Multi-turn tool conversations
- [ ] Multiple tools in single response
- [ ] Mixed text + tool responses

---

## Files Modified

1. **src/clio/providers/anthropic.py**
   - Added `_convert_messages_to_anthropic()` (lines 148-214)
   - Added `_convert_tools_to_anthropic()` (lines 216-241)
   - Updated `chat()` to use converter (line 43)
   - Updated `stream_chat()` to use converter (line 81)

2. **src/clio/providers/capabilities.py**
   - Added Claude 4.5 family models (lines 44-50)
   - Added Claude 3.7 family models (lines 52-54)

3. **src/clio/providers/base.py**
   - Added canonical format documentation in docstring

---

## Lessons Learned

1. **Read the docs first** - Would have saved time to fetch official docs before implementing
2. **Format normalization is critical** - Provider-agnostic systems need translation layers
3. **Test incrementally** - Each error revealed one piece of the format puzzle
4. **Content blocks are powerful** - Anthropic's approach allows mixing text/tools/images in single message
5. **Conversation history is tricky** - Must convert stored messages when switching providers

---

## Future Considerations

1. **Gemini provider** - Will need similar message conversion for Google's format
2. **Streaming tool calls** - May need special handling for streamed tool_use blocks
3. **Image support** - Anthropic supports images in content blocks, could add later
4. **Caching** - Anthropic supports prompt caching with `cache_control`, could optimize
5. **Reasoning models** - DeepSeek R1 has `reasoning_content`, similar to extended format
