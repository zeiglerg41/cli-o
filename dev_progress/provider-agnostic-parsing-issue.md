# Provider-Agnostic Response Parsing Issue

**Date:** 2025-12-31
**Status:** CRITICAL BUG - Blocks Anthropic provider usage

---

## Problem

**Current state:** Agent core (`agent/core.py`) hardcodes OpenAI response format expectations.

**Evidence:**
```python
# Line 400 in agent/core.py
if not response.get("choices") or len(response["choices"]) == 0:
    error_msg = f"❌ Invalid API response: No choices returned\nFull response: {response}"
```

**Anthropic response format:**
```json
{
  "id": "msg_01AcDHF5w6hAdbCPCTiNrx4X",
  "model": "claude-sonnet-4-5-20250929",
  "role": "assistant",
  "content": [{"type": "text", "text": "Hi."}],
  "stop_reason": "end_turn",
  "usage": {"input_tokens": 246, "output_tokens": 5}
}
```

**OpenAI response format:**
```json
{
  "id": "chatcmpl-...",
  "choices": [
    {
      "message": {
        "role": "assistant",
        "content": "Hi."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {"prompt_tokens": 246, "completion_tokens": 5}
}
```

**Result:** Anthropic provider fails with "No choices returned" even though API call succeeds.

---

## Root Cause

**Design flaw:** Agent expects provider to return OpenAI format, but providers return their native formats.

**Current architecture:**
1. Provider makes API call
2. Provider returns native API response (Anthropic format)
3. Agent expects OpenAI format (fails!)

**Where it breaks:**
- `agent/core.py` line 400: Expects `response["choices"]`
- `agent/core.py` line 405: Expects `response["choices"][0]`
- `agent/core.py` line 408+: Expects `choice["message"]["content"]`
- Tool call parsing: Expects OpenAI tool format

---

## Solution Options

### Option 1: Normalize in Provider (Recommended)
**Each provider converts its response to a standard format before returning.**

**Pros:**
- Agent code stays simple
- Single source of truth for response structure
- Easy to add new providers

**Cons:**
- Providers do extra work
- Need to define canonical format

**Implementation:**
```python
# In each provider's chat() method:
async def chat(self, messages, model, tools=None, **kwargs) -> Dict[str, Any]:
    # Make API call
    native_response = await self.client.chat(...)

    # Convert to canonical format
    return self._normalize_response(native_response)
```

**Canonical response format (based on OpenAI for compatibility):**
```python
{
    "choices": [
        {
            "message": {
                "role": "assistant",
                "content": str,
                "tool_calls": [...]  # Optional
            },
            "finish_reason": str
        }
    ],
    "usage": {
        "prompt_tokens": int,
        "completion_tokens": int
    }
}
```

---

### Option 2: Provider-Specific Parsing in Agent
**Agent checks provider type and parses accordingly.**

**Pros:**
- Providers stay clean

**Cons:**
- Agent has provider-specific logic (bad abstraction)
- Harder to add new providers
- Violates separation of concerns

**Implementation:**
```python
# In agent/core.py (BAD DESIGN)
if self.provider_type == "anthropic":
    content = response["content"][0]["text"]
elif self.provider_type == "openai":
    content = response["choices"][0]["message"]["content"]
```

❌ **Not recommended**

---

### Option 3: Response Adapter Layer
**Create a separate adapter that converts responses.**

**Pros:**
- Clean separation
- Testable

**Cons:**
- Extra layer of abstraction
- More files to maintain

**Implementation:**
```python
# New file: providers/adapters.py
class ResponseAdapter:
    @staticmethod
    def normalize(provider_type: str, response: Dict) -> Dict:
        if provider_type == "anthropic":
            return AnthropicAdapter.to_canonical(response)
        elif provider_type == "openai":
            return response  # Already canonical
```

---

## Recommended Approach

**Use Option 1: Normalize in Provider**

**Why:**
- Follows existing pattern (providers already have format conversion methods)
- Provider knows best how to convert its own format
- Agent stays provider-agnostic
- Easy to test

**Already exists partially:**
- `AnthropicProvider` has `format_tools_for_api()` - converts TO Anthropic format
- Just need reverse: convert FROM Anthropic format

---

## Files to Change

### 1. `providers/base.py`
Add abstract method or document canonical response format:
```python
class Provider(ABC):
    @abstractmethod
    async def chat(self, messages, model, tools=None, **kwargs) -> Dict[str, Any]:
        """Return response in canonical format (OpenAI-compatible).

        Canonical format:
        {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": str,
                    "tool_calls": [...]  # Optional
                },
                "finish_reason": str
            }],
            "usage": {
                "prompt_tokens": int,
                "completion_tokens": int
            }
        }
        """
        pass
```

### 2. `providers/anthropic.py`
Update `chat()` method to return canonical format:
```python
async def chat(self, ...):
    response = await self.client.messages.create(**params)

    # Convert to canonical OpenAI-compatible format
    return self._to_canonical_format(response)

def _to_canonical_format(self, anthropic_response) -> Dict[str, Any]:
    """Convert Anthropic response to canonical format."""
    # Extract text content
    text_blocks = [
        block.text
        for block in anthropic_response.content
        if block.type == "text"
    ]
    content = "".join(text_blocks)

    # Extract tool calls if any
    tool_calls = [
        {
            "id": block.id,
            "type": "function",
            "function": {
                "name": block.name,
                "arguments": json.dumps(block.input)
            }
        }
        for block in anthropic_response.content
        if block.type == "tool_use"
    ]

    return {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": content,
                **({"tool_calls": tool_calls} if tool_calls else {})
            },
            "finish_reason": anthropic_response.stop_reason
        }],
        "usage": {
            "prompt_tokens": anthropic_response.usage.input_tokens,
            "completion_tokens": anthropic_response.usage.output_tokens
        }
    }
```

### 3. `providers/openai_compatible.py`
Already returns correct format (no changes needed).

### 4. `agent/core.py`
Remove provider-specific assumptions (already correct if providers normalize).

---

## Testing Plan

1. **Test with OpenAI:** Ensure no regression
2. **Test with Anthropic:** Verify text responses work
3. **Test with Anthropic + tools:** Verify tool calling works
4. **Test with Ollama:** Ensure local models still work

---

## Notes

- This should have been caught earlier in provider design
- All new providers MUST normalize responses in their `chat()` method
- Consider adding provider response format tests to prevent regression
- Document canonical format in `providers/README.md` (create if needed)

---

## Action Items

- [ ] Document canonical response format in `base.py`
- [ ] Update `anthropic.py` to normalize responses
- [ ] Test Anthropic provider with text responses
- [ ] Test Anthropic provider with tool calls
- [ ] Verify OpenAI and Ollama still work
- [ ] Add provider response tests
