# All Provider Response Formats - Comprehensive Analysis

**Date:** 2025-12-31
**Purpose:** Document ALL major LLM provider response formats to build truly provider-agnostic system

---

## Provider Categories

### ✅ Category 1: OpenAI-Compatible (No Changes Needed)
These providers use OpenAI's exact API format. Already work with `OpenAICompatibleProvider`.

1. **OpenAI** - Native
2. **Grok (xAI)** - Fully OpenAI-compatible
3. **Ollama** - OpenAI-compatible endpoint
4. **OpenWebUI** - OpenAI-compatible
5. **vLLM** - OpenAI-compatible
6. **Together AI** - OpenAI-compatible
7. **Fireworks AI** - OpenAI-compatible

**Status:** ✅ Already working via `openai-compatible` provider type

---

### ⚠️ Category 2: OpenAI-Compatible with Extensions
These providers add extra fields but maintain OpenAI structure.

#### **DeepSeek** (including R1)
**Base URL:** `https://api.deepseek.com`
**Special feature:** Reasoning models add `reasoning_content` field

**Response format:**
```json
{
  "id": "chatcmpl-xxx",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Final answer here",
        "reasoning_content": "Chain-of-thought reasoning (R1 models only)"
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 100,
    "completion_tokens": 50,
    "total_tokens": 150
  }
}
```

**Models:**
- `deepseek-chat` - V3.2 non-thinking
- `deepseek-reasoner` - V3.2 with reasoning (R1)
- `deepseek-coder`

**Handling strategy:**
- Use `openai-compatible` provider type
- Extract `reasoning_content` if present and optionally display to user
- Concatenate `reasoning_content + content` or keep separate based on user preference

**Status:** ✅ Can use existing provider, add reasoning display later

---

### ❌ Category 3: Native Format (Needs Custom Provider)

#### **Anthropic (Claude)**
**Base URL:** `https://api.anthropic.com`
**Currently:** Partially implemented but broken

**Response format:**
```json
{
  "id": "msg_01AcDHF5w6hAdbCPCTiNrx4X",
  "model": "claude-sonnet-4-5-20250929",
  "role": "assistant",
  "content": [
    {
      "type": "text",
      "text": "Response content here"
    },
    {
      "type": "tool_use",
      "id": "toolu_01XYZ",
      "name": "tool_name",
      "input": {"arg": "value"}
    }
  ],
  "stop_reason": "end_turn",
  "usage": {
    "input_tokens": 246,
    "output_tokens": 5
  }
}
```

**Key differences:**
- No `choices` array - direct response
- `content` is array of blocks (text, tool_use)
- Tool calls are inline content blocks, not separate field
- System messages passed as separate parameter, not in messages array
- Tool results go in user messages with `tool_result` type

**Status:** ❌ Broken - needs normalization

---

#### **Google Gemini**
**Base URL:** `https://generativelanguage.googleapis.com/v1beta`
**Currently:** Not implemented

**Response format:**
```json
{
  "candidates": [
    {
      "content": {
        "role": "model",
        "parts": [
          {
            "text": "response text here"
          },
          {
            "functionCall": {
              "name": "tool_name",
              "args": {"arg": "value"}
            }
          }
        ]
      },
      "finishReason": "STOP",
      "safetyRatings": [...]
    }
  ],
  "usageMetadata": {
    "promptTokenCount": 10,
    "candidatesTokenCount": 50,
    "totalTokenCount": 60
  }
}
```

**Key differences:**
- `candidates` array (not `choices`)
- `content.parts` array containing text/functionCall objects
- `finishReason` is uppercase enum (STOP, MAX_TOKENS, SAFETY)
- Token counts have different field names
- Role is `model` not `assistant`
- Tool calls are `functionCall` objects in parts

**Models:**
- `gemini-2.0-flash`
- `gemini-2.0-flash-thinking-exp`
- `gemini-1.5-pro`
- `gemini-1.5-flash`

**Status:** ❌ Not implemented

---

## Canonical Response Format (OpenAI-Compatible)

**All providers MUST normalize to this format before returning to Agent:**

```python
{
    "choices": [
        {
            "index": 0,
            "message": {
                "role": "assistant",
                "content": str,  # Main response text
                "tool_calls": [  # Optional - only if tools used
                    {
                        "id": str,
                        "type": "function",
                        "function": {
                            "name": str,
                            "arguments": str  # JSON string
                        }
                    }
                ],
                "reasoning_content": str  # Optional - for reasoning models
            },
            "finish_reason": str  # "stop", "length", "tool_calls", etc.
        }
    ],
    "usage": {
        "prompt_tokens": int,
        "completion_tokens": int,
        "total_tokens": int  # Optional, can be calculated
    },
    "id": str,  # Optional
    "model": str  # Optional
}
```

---

## Normalization Implementation Plan

### 1. Update Base Provider
```python
# providers/base.py
class Provider(ABC):
    @abstractmethod
    async def chat(self, messages, model, tools=None, **kwargs) -> Dict[str, Any]:
        """Make API call and return response in CANONICAL format.

        Canonical format matches OpenAI structure for compatibility.
        See: all-providers-response-formats.md
        """
        pass

    def _normalize_response(self, native_response: Any) -> Dict[str, Any]:
        """Convert provider-specific response to canonical format.

        Override this in each provider implementation.
        """
        raise NotImplementedError("Provider must implement _normalize_response()")
```

### 2. Fix Anthropic Provider
```python
# providers/anthropic.py
async def chat(self, messages, model, tools=None, **kwargs):
    # Make API call
    response = await self.client.messages.create(...)

    # Normalize to canonical format
    return self._normalize_response(response)

def _normalize_response(self, anthropic_response) -> Dict[str, Any]:
    """Convert Anthropic format to canonical OpenAI format."""
    # Extract text blocks
    text_parts = [
        block.text
        for block in anthropic_response.content
        if block.type == "text"
    ]
    content = "".join(text_parts)

    # Extract tool calls
    tool_calls = []
    for block in anthropic_response.content:
        if block.type == "tool_use":
            tool_calls.append({
                "id": block.id,
                "type": "function",
                "function": {
                    "name": block.name,
                    "arguments": json.dumps(block.input)
                }
            })

    message = {
        "role": "assistant",
        "content": content
    }
    if tool_calls:
        message["tool_calls"] = tool_calls

    return {
        "choices": [{
            "index": 0,
            "message": message,
            "finish_reason": anthropic_response.stop_reason
        }],
        "usage": {
            "prompt_tokens": anthropic_response.usage.input_tokens,
            "completion_tokens": anthropic_response.usage.output_tokens,
            "total_tokens": (
                anthropic_response.usage.input_tokens +
                anthropic_response.usage.output_tokens
            )
        },
        "id": anthropic_response.id,
        "model": anthropic_response.model
    }
```

### 3. Create Gemini Provider
```python
# providers/gemini.py (NEW FILE)
class GeminiProvider(Provider):
    def __init__(self, config):
        try:
            import google.generativeai as genai
        except ImportError:
            raise ImportError("google-generativeai package required")

        genai.configure(api_key=config["api_key"])
        self.client = genai

    async def chat(self, messages, model, tools=None, **kwargs):
        # Convert messages to Gemini format
        gemini_messages = self._convert_messages(messages)

        # Make API call
        model_instance = self.client.GenerativeModel(model)
        response = await model_instance.generate_content_async(
            gemini_messages,
            tools=self._convert_tools(tools) if tools else None
        )

        # Normalize
        return self._normalize_response(response)

    def _normalize_response(self, gemini_response) -> Dict[str, Any]:
        """Convert Gemini format to canonical OpenAI format."""
        candidate = gemini_response.candidates[0]

        # Extract text parts
        text_parts = [
            part.text
            for part in candidate.content.parts
            if hasattr(part, "text")
        ]
        content = "".join(text_parts)

        # Extract function calls
        tool_calls = []
        for part in candidate.content.parts:
            if hasattr(part, "function_call"):
                fc = part.function_call
                tool_calls.append({
                    "id": f"call_{hash(fc.name)}",  # Gemini doesn't provide IDs
                    "type": "function",
                    "function": {
                        "name": fc.name,
                        "arguments": json.dumps(dict(fc.args))
                    }
                })

        message = {
            "role": "assistant",
            "content": content
        }
        if tool_calls:
            message["tool_calls"] = tool_calls

        # Map finish reason
        finish_reason_map = {
            "STOP": "stop",
            "MAX_TOKENS": "length",
            "SAFETY": "content_filter"
        }
        finish_reason = finish_reason_map.get(
            candidate.finish_reason.name,
            "stop"
        )

        return {
            "choices": [{
                "index": 0,
                "message": message,
                "finish_reason": finish_reason
            }],
            "usage": {
                "prompt_tokens": gemini_response.usage_metadata.prompt_token_count,
                "completion_tokens": gemini_response.usage_metadata.candidates_token_count,
                "total_tokens": gemini_response.usage_metadata.total_token_count
            },
            "model": gemini_response.model_version
        }
```

### 4. Update Factory
```python
# providers/__init__.py
def create_provider(provider_type: str, config: Dict[str, Any]) -> Provider:
    if provider_type == "openai-compatible":
        return OpenAICompatibleProvider(config)
    elif provider_type == "openai":
        if "base_url" not in config:
            config["base_url"] = "https://api.openai.com/v1"
        return OpenAICompatibleProvider(config)
    elif provider_type == "anthropic":
        return AnthropicProvider(config)
    elif provider_type == "gemini":
        return GeminiProvider(config)
    elif provider_type == "deepseek":
        # DeepSeek is OpenAI-compatible with extensions
        if "base_url" not in config:
            config["base_url"] = "https://api.deepseek.com"
        return OpenAICompatibleProvider(config)
    elif provider_type == "grok":
        # Grok is fully OpenAI-compatible
        if "base_url" not in config:
            config["base_url"] = "https://api.x.ai/v1"
        return OpenAICompatibleProvider(config)
    else:
        raise ValueError(f"Unknown provider type: {provider_type}")
```

---

## Provider Support Matrix

| Provider | Status | Type | Notes |
|----------|--------|------|-------|
| OpenAI | ✅ Working | openai | Native format |
| Grok (xAI) | ✅ Working | grok | OpenAI-compatible, auto-configured |
| Ollama | ✅ Working | openai-compatible | Local models |
| OpenWebUI | ✅ Working | openai-compatible | Self-hosted |
| DeepSeek | ✅ Working | deepseek | OpenAI-compatible, auto-configured |
| Anthropic | ✅ Working | anthropic | Native format with normalization |
| Gemini | ✅ Working | gemini | Native format with normalization |
| Together AI | ✅ Working | openai-compatible | Cloud hosting |
| Fireworks | ✅ Working | openai-compatible | Cloud hosting |

---

## Implementation Priority

### Phase 1: Fix Existing (HIGH)
1. ✅ Fix Anthropic provider normalization
2. ✅ Test with Claude 4.5 models
3. ✅ Verify tool calling works

### Phase 2: Add Gemini (MEDIUM)
1. ✅ Create GeminiProvider class
2. ✅ Implement message/tool conversion
3. ✅ Add to factory
4. ✅ Add config examples

### Phase 3: DeepSeek Reasoning (LOW)
1. ⏸️ Detect `reasoning_content` field
2. ⏸️ Add UI option to show/hide reasoning
3. ⏸️ Store reasoning in database separately

---

## Testing Checklist

For EACH provider:
- [ ] Simple text response
- [ ] Tool calling (single tool)
- [ ] Tool calling (multiple tools)
- [ ] Multi-turn conversation
- [ ] Token counting accuracy
- [ ] Error handling
- [ ] Streaming (if supported)

---

## Dependencies to Install

```bash
# Anthropic (already installed)
pipx inject clio anthropic

# Gemini
pipx inject clio google-generativeai

# DeepSeek (uses OpenAI SDK, already available)
# No extra deps needed
```

---

## Notes

- Keep canonical format as close to OpenAI as possible for maximum compatibility
- Document extensions (like `reasoning_content`) but don't break compatibility
- Each provider handles its own normalization - Agent stays clean
- Test with real API calls, not mocked responses
- Consider caching provider instances instead of recreating on model switch
