# Provider Configuration Examples

**Date:** 2025-12-31
**Purpose:** Complete examples for configuring all supported providers in `~/.clio/config.json`

---

## Configuration File Location

`~/.clio/config.json`

---

## Provider Types

### 1. OpenAI (Native)

```json
{
  "providers": {
    "openai": {
      "type": "openai",
      "baseURL": null,
      "apiKey": "sk-proj-...",
      "adminApiKey": "sk-proj-...",
      "headers": null,
      "models": [
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4-turbo",
        "o1",
        "o1-mini",
        "o3-mini"
      ],
      "hostname": "OpenAI"
    }
  }
}
```

**Notes:**
- `baseURL` is automatically set to `https://api.openai.com/v1`
- `adminApiKey` is optional, only needed for billing API access with `/usage` command
- Supports all GPT-4, GPT-3.5-turbo, and o1/o3 models with tool calling

---

### 2. Anthropic (Claude)

```json
{
  "providers": {
    "anthropic": {
      "type": "anthropic",
      "baseURL": null,
      "apiKey": "sk-ant-api03-...",
      "adminApiKey": null,
      "headers": null,
      "models": [
        "claude-opus-4-5-20251101",
        "claude-sonnet-4-5-20250929",
        "claude-haiku-4-5-20251001",
        "claude-3-7-sonnet-20250219",
        "claude-3-5-sonnet-20241022",
        "claude-3-5-haiku-20241022"
      ],
      "hostname": "Anthropic"
    }
  }
}
```

**Notes:**
- Uses native Anthropic API (not OpenAI-compatible)
- Responses are automatically normalized to canonical format
- All Claude 3+, 3.5+, 3.7+, and 4.5+ models support tool calling
- Get API key from https://console.anthropic.com/

**Dependencies:**
```bash
pipx inject clio anthropic
```

---

### 3. Google Gemini

```json
{
  "providers": {
    "gemini": {
      "type": "gemini",
      "baseURL": null,
      "apiKey": "AIza...",
      "adminApiKey": null,
      "headers": null,
      "models": [
        "gemini-2.0-flash",
        "gemini-2.0-flash-thinking-exp",
        "gemini-1.5-pro",
        "gemini-1.5-flash"
      ],
      "hostname": "Google Gemini"
    }
  }
}
```

**Notes:**
- Uses native Google Generative AI API
- Responses are automatically normalized to canonical format
- All Gemini 1.5+ and 2.0+ models support tool calling
- Get API key from https://makersuite.google.com/app/apikey

**Dependencies:**
```bash
pipx inject clio google-generativeai
```

---

### 4. Grok (xAI)

```json
{
  "providers": {
    "grok": {
      "type": "grok",
      "baseURL": null,
      "apiKey": "xai-...",
      "adminApiKey": null,
      "headers": null,
      "models": [
        "grok-beta",
        "grok-2-latest"
      ],
      "hostname": "xAI Grok"
    }
  }
}
```

**Notes:**
- Fully OpenAI-compatible API
- `baseURL` is automatically set to `https://api.x.ai/v1`
- Uses same tool calling format as OpenAI
- Get API key from https://console.x.ai/

---

### 5. DeepSeek (including R1 reasoning models)

```json
{
  "providers": {
    "deepseek": {
      "type": "deepseek",
      "baseURL": null,
      "apiKey": "sk-...",
      "adminApiKey": null,
      "headers": null,
      "models": [
        "deepseek-chat",
        "deepseek-reasoner",
        "deepseek-coder"
      ],
      "hostname": "DeepSeek"
    }
  }
}
```

**Notes:**
- OpenAI-compatible with extension fields
- `baseURL` is automatically set to `https://api.deepseek.com`
- `deepseek-reasoner` adds `reasoning_content` field (not yet displayed in UI)
- Get API key from https://platform.deepseek.com/

---

### 6. Ollama (Local Models)

```json
{
  "providers": {
    "ollama": {
      "type": "openai-compatible",
      "baseURL": "http://localhost:11434/v1",
      "apiKey": "ollama",
      "adminApiKey": null,
      "headers": null,
      "models": [
        "llama3.1:8b",
        "llama3.1:70b",
        "mistral-nemo",
        "command-r"
      ],
      "hostname": "Ollama (Local)"
    }
  }
}
```

**Notes:**
- Uses OpenAI-compatible endpoint
- Requires Ollama running locally
- API key can be any string (not validated)
- Only certain models support tool calling (llama3.1+, mistral-nemo, command-r, firefunction-v2)

---

### 7. OpenWebUI (Self-Hosted)

```json
{
  "providers": {
    "openwebui": {
      "type": "openai-compatible",
      "baseURL": "http://localhost:8080/v1",
      "apiKey": "your-token",
      "adminApiKey": null,
      "headers": null,
      "models": [
        "gpt-4o",
        "llama3.1:70b"
      ],
      "hostname": "OpenWebUI"
    }
  }
}
```

**Notes:**
- OpenAI-compatible API
- Can proxy to multiple providers
- Get token from OpenWebUI admin panel

---

### 8. Generic OpenAI-Compatible Provider

```json
{
  "providers": {
    "custom": {
      "type": "openai-compatible",
      "baseURL": "https://your-provider.com/v1",
      "apiKey": "your-api-key",
      "adminApiKey": null,
      "headers": {
        "X-Custom-Header": "value"
      },
      "models": [
        "model-name-1",
        "model-name-2"
      ],
      "hostname": "Custom Provider"
    }
  }
}
```

**Notes:**
- Works with any OpenAI-compatible API
- Custom headers can be added if needed
- Supports tool calling if the underlying model does

---

## Complete Multi-Provider Example

```json
{
  "providers": {
    "openai": {
      "type": "openai",
      "baseURL": null,
      "apiKey": "sk-proj-...",
      "adminApiKey": "sk-proj-...",
      "headers": null,
      "models": [
        "gpt-4o",
        "gpt-4o-mini",
        "o3-mini"
      ],
      "hostname": "OpenAI"
    },
    "anthropic": {
      "type": "anthropic",
      "baseURL": null,
      "apiKey": "sk-ant-api03-...",
      "adminApiKey": null,
      "headers": null,
      "models": [
        "claude-sonnet-4-5-20250929",
        "claude-opus-4-5-20251101",
        "claude-haiku-4-5-20251001"
      ],
      "hostname": "Anthropic"
    },
    "gemini": {
      "type": "gemini",
      "baseURL": null,
      "apiKey": "AIza...",
      "adminApiKey": null,
      "headers": null,
      "models": [
        "gemini-2.0-flash",
        "gemini-1.5-pro"
      ],
      "hostname": "Google Gemini"
    },
    "grok": {
      "type": "grok",
      "baseURL": null,
      "apiKey": "xai-...",
      "adminApiKey": null,
      "headers": null,
      "models": [
        "grok-2-latest"
      ],
      "hostname": "xAI Grok"
    },
    "deepseek": {
      "type": "deepseek",
      "baseURL": null,
      "apiKey": "sk-...",
      "adminApiKey": null,
      "headers": null,
      "models": [
        "deepseek-chat",
        "deepseek-reasoner"
      ],
      "hostname": "DeepSeek"
    },
    "ollama": {
      "type": "openai-compatible",
      "baseURL": "http://localhost:11434/v1",
      "apiKey": "ollama",
      "adminApiKey": null,
      "headers": null,
      "models": [
        "llama3.1:70b"
      ],
      "hostname": "Ollama (Local)"
    }
  },
  "defaultProvider": "openai",
  "defaultModel": "gpt-4o",
  "theme": "dark",
  "colors": {
    "user": "cyan",
    "assistant": "green",
    "system": "yellow",
    "tool": "magenta"
  }
}
```

---

## Tool Calling Support Matrix

| Provider | Type | Tool Calling | Notes |
|----------|------|--------------|-------|
| OpenAI | Native | ✅ GPT-3.5+, GPT-4+, o1+ | Full support |
| Anthropic | Native | ✅ Claude 3+, 3.5+, 3.7+, 4.5+ | Full support |
| Gemini | Native | ✅ Gemini 1.5+, 2.0+ | Full support |
| Grok | OpenAI-compatible | ✅ All models | Via OpenAI format |
| DeepSeek | OpenAI-compatible | ✅ All models | Via OpenAI format |
| Ollama | OpenAI-compatible | ⚠️ Limited | Only llama3.1+, mistral-nemo, command-r |
| OpenWebUI | OpenAI-compatible | ⚠️ Depends | Depends on backend model |

---

## Installation Commands

```bash
# Core dependencies (already installed with clio)
# - openai (for OpenAI-compatible providers)

# Anthropic
pipx inject clio anthropic

# Google Gemini
pipx inject clio google-generativeai

# All optional providers
pipx inject clio anthropic google-generativeai
```

---

## Switching Providers/Models at Runtime

```bash
# Switch provider
/provider anthropic

# Switch model
/model claude-sonnet-4-5-20250929

# List available providers
/providers

# List models for current provider
/models
```

---

## Troubleshooting

### Provider not found
**Error:** `Unknown provider type: xyz`
**Fix:** Check that `type` field matches supported types: `openai`, `anthropic`, `gemini`, `grok`, `deepseek`, `openai-compatible`

### Tool calling disabled warning
**Error:** `Model 'xyz' does not support tool calling`
**Fix:** Check `capabilities.py` to verify model is listed, or switch to a model that supports tools

### Missing dependency
**Error:** `ImportError: No module named 'anthropic'`
**Fix:** Install the provider package: `pipx inject clio anthropic`

### Invalid API response
**Error:** `No choices returned`
**Fix:** This means the provider didn't normalize the response correctly. Report as a bug if using a supported provider.

---

## Testing Checklist

For each new provider, verify:
- [ ] Simple text response works
- [ ] Tool calling works (single tool)
- [ ] Tool calling works (multiple tools)
- [ ] Multi-turn conversation works
- [ ] Token counting is accurate
- [ ] Error handling is graceful
- [ ] Model listing works (`/models` command)
- [ ] Provider switching works (`/provider` command)
