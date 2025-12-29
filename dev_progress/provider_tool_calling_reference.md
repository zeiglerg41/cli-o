# Provider Tool Calling API Reference

This document provides a comprehensive comparison of tool calling APIs across OpenAI, Anthropic, and Ollama for building a unified provider abstraction layer.

## Executive Summary

### Key Differences

| Feature | OpenAI | Anthropic Claude | Ollama |
|---------|--------|------------------|--------|
| API Format | `tools` parameter | `tools` parameter | `tools` parameter (OpenAI-compatible) |
| Tool Definition | JSON Schema with `type: "function"` | JSON Schema with `input_schema` | Same as OpenAI |
| Response Format | `tool_calls` array in message | `tool_use` content blocks | `tool_calls` array (OpenAI-compatible) |
| Tool Results | `tool` role message | `tool_result` content blocks | `tool` role message |
| Parallel Calls | Supported (controllable with `parallel_tool_calls`) | Supported | Supported |
| Structured Outputs | `strict: true` (2024+) | Beta feature (2025) | Not supported |
| Model Support | GPT-4, GPT-4 Turbo, GPT-4o, GPT-3.5-turbo (0613+) | All Claude 3+ models | Llama 3.1, Mistral Nemo, Firefunction v2, Command-R+ |

---

## 1. OpenAI Tool Calling API

### Request Format

```json
{
  "model": "gpt-4o",
  "messages": [
    {
      "role": "user",
      "content": "What is the weather in San Francisco?"
    }
  ],
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "get_weather",
        "description": "Get current weather for a location",
        "parameters": {
          "type": "object",
          "properties": {
            "location": {
              "type": "string",
              "description": "City and country, e.g. San Francisco, CA"
            },
            "unit": {
              "type": "string",
              "enum": ["celsius", "fahrenheit"],
              "description": "Temperature unit"
            }
          },
          "required": ["location"],
          "additionalProperties": false
        },
        "strict": true
      }
    }
  ],
  "tool_choice": "auto"
}
```

### Response Format

```json
{
  "id": "chatcmpl-abc123",
  "object": "chat.completion",
  "created": 1699896916,
  "model": "gpt-4o",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": null,
        "tool_calls": [
          {
            "id": "call_abc123",
            "type": "function",
            "function": {
              "name": "get_weather",
              "arguments": "{\"location\": \"San Francisco, CA\", \"unit\": \"fahrenheit\"}"
            }
          }
        ]
      },
      "finish_reason": "tool_calls"
    }
  ]
}
```

### Sending Tool Results Back

```json
{
  "model": "gpt-4o",
  "messages": [
    {
      "role": "user",
      "content": "What is the weather in San Francisco?"
    },
    {
      "role": "assistant",
      "content": null,
      "tool_calls": [
        {
          "id": "call_abc123",
          "type": "function",
          "function": {
            "name": "get_weather",
            "arguments": "{\"location\": \"San Francisco, CA\"}"
          }
        }
      ]
    },
    {
      "role": "tool",
      "tool_call_id": "call_abc123",
      "content": "{\"temperature\": 72, \"condition\": \"sunny\"}"
    }
  ]
}
```

### Key Features

- **Tool Choice Control**: `auto` (default), `none`, `required`, or specific function with `{"type": "function", "function": {"name": "my_function"}}`
- **Parallel Tool Calls**: Set `parallel_tool_calls: false` to ensure only one tool is called at a time
- **Strict Mode**: `strict: true` enables Structured Outputs (guarantees exact JSON Schema match)
- **Deprecated**: `functions` and `function_call` parameters (replaced by `tools` and `tool_choice`)

---

## 2. Anthropic Claude Tool Use API

### Request Format

```json
{
  "model": "claude-3-5-sonnet-20241022",
  "max_tokens": 1024,
  "messages": [
    {
      "role": "user",
      "content": "What is the weather in San Francisco?"
    }
  ],
  "tools": [
    {
      "name": "get_weather",
      "description": "Get current weather for a location",
      "input_schema": {
        "type": "object",
        "properties": {
          "location": {
            "type": "string",
            "description": "City and country, e.g. San Francisco, CA"
          },
          "unit": {
            "type": "string",
            "enum": ["celsius", "fahrenheit"],
            "description": "Temperature unit"
          }
        },
        "required": ["location"]
      }
    }
  ],
  "tool_choice": {"type": "auto"}
}
```

### Response Format

```json
{
  "id": "msg_01Aq9w938a90dw8q",
  "model": "claude-3-5-sonnet-20241022",
  "stop_reason": "tool_use",
  "role": "assistant",
  "content": [
    {
      "type": "text",
      "text": "I'll check the weather for you."
    },
    {
      "type": "tool_use",
      "id": "toolu_01A09q90i40ji9i3",
      "name": "get_weather",
      "input": {
        "location": "San Francisco, CA",
        "unit": "fahrenheit"
      }
    }
  ]
}
```

### Sending Tool Results Back

```json
{
  "model": "claude-3-5-sonnet-20241022",
  "max_tokens": 1024,
  "messages": [
    {
      "role": "user",
      "content": "What is the weather in San Francisco?"
    },
    {
      "role": "assistant",
      "content": [
        {
          "type": "text",
          "text": "I'll check the weather for you."
        },
        {
          "type": "tool_use",
          "id": "toolu_01A09q90i40ji9i3",
          "name": "get_weather",
          "input": {
            "location": "San Francisco, CA"
          }
        }
      ]
    },
    {
      "role": "user",
      "content": [
        {
          "type": "tool_result",
          "tool_use_id": "toolu_01A09q90i40ji9i3",
          "content": "{\"temperature\": 72, \"condition\": \"sunny\"}"
        }
      ]
    }
  ],
  "tools": [...]
}
```

### Key Features

- **Content Blocks**: Responses can contain multiple content blocks (text + tool_use)
- **Tool Choice**: `{"type": "auto"}`, `{"type": "any"}`, `{"type": "tool", "name": "tool_name"}`
- **Stop Reasons**: `tool_use` when model wants to use a tool
- **Beta Features (2025)**:
  - **Structured Outputs**: `anthropic-beta: structured-outputs-2025-11-13`
  - **Advanced Tool Use**: `advanced-tool-use-2025-11-20` (programmatic tool calling)
  - **Tool Search**: `tool-search-tool-2025-10-19` (defer_loading for thousands of tools)
  - **Fine-grained Streaming**: `fine-grained-tool-streaming-2025-05-14`

---

## 3. Ollama Tool Calling API

### Request Format (OpenAI-Compatible)

```json
{
  "model": "llama3.1",
  "messages": [
    {
      "role": "user",
      "content": "What is the weather in San Francisco?"
    }
  ],
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "get_weather",
        "description": "Get current weather for a location",
        "parameters": {
          "type": "object",
          "properties": {
            "location": {
              "type": "string",
              "description": "City and country"
            }
          },
          "required": ["location"]
        }
      }
    }
  ]
}
```

### Response Format (OpenAI-Compatible)

Same as OpenAI - uses `tool_calls` array in message.

### Key Features

- **OpenAI Compatibility**: Uses OpenAI's endpoint format (`/v1/chat/completions`)
- **Supported Models**: Llama 3.1, Mistral Nemo, Firefunction v2, Command-R+
- **Limitations**:
  - No streaming tool calls (planned)
  - No tool_choice parameter (planned)
- **Usage**: Can use OpenAI Python SDK by pointing to `http://localhost:11434/v1`

---

## 4. Normalization Patterns for Abstraction Layer

### Tool Definition Normalization

**Internal Format (Canonical)**:
```python
{
    "name": str,
    "description": str,
    "parameters": {  # JSON Schema
        "type": "object",
        "properties": {...},
        "required": [...]
    }
}
```

**Provider-Specific Transformations**:

1. **OpenAI**: Wrap in `{"type": "function", "function": {...}}`
2. **Anthropic**: Rename `parameters` → `input_schema`
3. **Ollama**: Same as OpenAI

### Response Normalization

**Internal Format (Canonical)**:
```python
{
    "type": "tool_call",  # or "text"
    "id": str,
    "name": str,
    "arguments": dict  # Already parsed, not JSON string
}
```

**Provider-Specific Parsing**:

1. **OpenAI**:
   - Extract from `message.tool_calls[i].function`
   - Parse `arguments` from JSON string to dict
   - Use `tool_calls[i].id` as id

2. **Anthropic**:
   - Iterate through `content` blocks
   - Filter for `type == "tool_use"`
   - Use `input` directly (already dict)
   - Use block `id` as id

3. **Ollama**: Same as OpenAI

### Tool Result Normalization

**Internal Format**:
```python
{
    "tool_call_id": str,
    "result": str  # JSON-serialized result
}
```

**Provider-Specific Formatting**:

1. **OpenAI**:
```python
{
    "role": "tool",
    "tool_call_id": tool_call_id,
    "content": result
}
```

2. **Anthropic**:
```python
{
    "role": "user",
    "content": [
        {
            "type": "tool_result",
            "tool_use_id": tool_call_id,
            "content": result
        }
    ]
}
```

3. **Ollama**: Same as OpenAI

---

## 5. Capability Detection

### Tool Calling Support Matrix

```python
TOOL_SUPPORT = {
    "openai": {
        "gpt-4": True,
        "gpt-4-turbo": True,
        "gpt-4o": True,
        "gpt-4o-mini": True,
        "gpt-3.5-turbo": True,  # 0613+
        "gpt-3.5-turbo-0613": True,
        "o1": True,  # Limited support
    },
    "anthropic": {
        "claude-3-5-sonnet-20241022": True,
        "claude-3-5-haiku-20241022": True,
        "claude-3-opus-20240229": True,
        "claude-3-sonnet-20240229": True,
        "claude-3-haiku-20240307": True,
    },
    "ollama": {
        "llama3.1": True,
        "mistral-nemo": True,
        "firefunction-v2": True,
        "command-r-plus": True,
    }
}
```

### Detection Strategy

```python
def supports_tools(provider: str, model: str) -> bool:
    """Check if a model supports tool calling."""
    if provider not in TOOL_SUPPORT:
        return False

    model_lower = model.lower()

    # Exact match
    if model_lower in TOOL_SUPPORT[provider]:
        return TOOL_SUPPORT[provider][model_lower]

    # Prefix match (e.g., "gpt-4-turbo-2024-04-09" matches "gpt-4-turbo")
    for supported_model in TOOL_SUPPORT[provider]:
        if model_lower.startswith(supported_model):
            return True

    return False
```

---

## 6. Recommended Architecture

### Provider Interface

```python
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

class BaseLLMProvider(ABC):
    """Base class for all LLM providers with tool calling support."""

    @abstractmethod
    def supports_tools(self, model: str) -> bool:
        """Check if model supports tool calling."""
        pass

    @abstractmethod
    def format_tools(self, tools: List[Dict[str, Any]]) -> Any:
        """Convert canonical tool format to provider-specific format."""
        pass

    @abstractmethod
    def parse_response(self, response: Any) -> Dict[str, Any]:
        """Parse provider response into canonical format."""
        pass

    @abstractmethod
    def format_tool_result(self, tool_call_id: str, result: str) -> Dict[str, Any]:
        """Format tool result for next request."""
        pass

    @abstractmethod
    async def chat(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Send chat request with optional tools."""
        pass
```

### Canonical Message Format

```python
# Internal message format used throughout clio
{
    "role": "user" | "assistant" | "system" | "tool",
    "content": str | List[Dict],  # Text or content blocks
    "tool_calls": [  # Only for assistant messages
        {
            "id": str,
            "name": str,
            "arguments": dict
        }
    ],
    "tool_call_id": str,  # Only for tool result messages
}
```

---

## 7. Testing Strategy

### Unit Tests

1. **Tool Definition Conversion**
   - Test canonical → OpenAI format
   - Test canonical → Anthropic format
   - Test canonical → Ollama format

2. **Response Parsing**
   - Test OpenAI tool_calls → canonical
   - Test Anthropic tool_use blocks → canonical
   - Test text-only responses

3. **Tool Result Formatting**
   - Test result → OpenAI message
   - Test result → Anthropic message

4. **Capability Detection**
   - Test known models (positive cases)
   - Test unknown models (negative cases)
   - Test model prefix matching

### Integration Tests

1. **Provider Switching**
   - Start conversation with OpenAI
   - Switch to Anthropic mid-conversation
   - Verify message format conversion

2. **Tool Execution Loop**
   - Mock tool execution
   - Test single tool call
   - Test parallel tool calls
   - Test multi-turn tool usage

3. **Error Handling**
   - Invalid tool arguments
   - Tool execution failures
   - Model doesn't support tools (graceful degradation)
   - Network failures

### Manual Testing Checklist

- [ ] OpenAI: GPT-4o with single tool call
- [ ] OpenAI: GPT-4o with parallel tool calls
- [ ] Anthropic: Claude 3.5 Sonnet with tool use
- [ ] Anthropic: Claude response with text + tool_use blocks
- [ ] Ollama: Llama 3.1 with tool calling
- [ ] Test model without tool support (warning/error)
- [ ] Test switching providers mid-conversation
- [ ] Test tool execution error handling
- [ ] Test streaming responses (if applicable)

---

## 8. Implementation Priority

### Phase 1: Core Abstraction
1. Create `BaseLLMProvider` interface
2. Implement canonical tool format
3. Add tool conversion for OpenAI (already supported via OpenAICompatibleProvider)
4. Add capability detection

### Phase 2: Anthropic Support
1. Create `AnthropicProvider` class
2. Implement tool definition conversion
3. Implement response parsing (content blocks)
4. Implement tool result formatting
5. Unit tests for Anthropic provider

### Phase 3: Enhanced Error Handling
1. Validate tool support before sending request
2. User warnings for unsupported models
3. Graceful degradation (disable tools if unsupported)
4. Better error messages

### Phase 4: Advanced Features
1. Streaming support for tool calls
2. Anthropic beta features (structured outputs, tool search)
3. OpenAI strict mode support
4. Tool choice control across providers

---

## References

- [OpenAI Function Calling Docs](https://platform.openai.com/docs/guides/function-calling)
- [Anthropic Tool Use Docs](https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview)
- [Ollama Tool Support Blog](https://ollama.com/blog/tool-support)
- [OpenAI Chat Completions API Reference](https://platform.openai.com/docs/api-reference/chat)
- [Anthropic Messages API Reference](https://docs.anthropic.com/en/api/messages)
