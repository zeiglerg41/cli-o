# 01 - Provider Abstraction Layer: Unified Tool Calling

**Status**: Ready for Development
**Created**: 2025-12-29
**Goal**: Enable clio to use ANY LLM provider (OpenAI, Anthropic, Ollama) with seamless tool calling support

---

## Problem

- clio currently only supports OpenAI-compatible providers
- No Anthropic (Claude) support
- No capability detection (can't warn users if model doesn't support tools)
- Different providers have different tool calling formats

---

## Solution

Create provider abstraction layer that:
1. **Normalizes tool definitions** - convert between provider formats automatically
2. **Detects capabilities** - warn users if model doesn't support tools
3. **Seamless switching** - change providers mid-conversation without breaking

---

## Architecture

**Pattern**: Single model for everything (context + reasoning + tool calling in agentic loop)

**Flow**:
```
User Input → Provider Abstraction → Format Tools → API Call → Parse Response → Execute Tools → Loop
```

**Key Components**:
- Canonical tool format (internal representation)
- Provider-specific adapters (convert to/from canonical)
- Capability registry (which models support tools)

---

## Documentation

See `dev_progress/` for complete reference:

1. **`provider_tool_calling_reference.md`**
   - Full API comparison (OpenAI vs Anthropic vs Ollama)
   - Request/response formats with JSON examples
   - Normalization patterns
   - Testing strategy

2. **`implementation_roadmap.md`**
   - 5-week phased plan
   - Week-by-week deliverables
   - Code snippets for each component
   - Manual testing checklist

---

## Quick Start

### Phase 1: Core Abstraction (Week 1)
- [ ] Create canonical schemas (`schemas.py`)
- [ ] Add capability detection (`capabilities.py`)
- [ ] Update base provider interface
- [ ] Update OpenAI provider to use new interface

### Phase 2: Anthropic Support (Week 2)
- [ ] Implement `AnthropicProvider` class
- [ ] Tool format conversion (parameters → input_schema)
- [ ] Response parsing (content blocks → canonical)
- [ ] Add to provider factory

### Phase 3: Integration (Week 3)
- [ ] Update Agent to check tool support
- [ ] Add user warnings for unsupported models
- [ ] Update config schema

### Phase 4: Testing (Week 4)
- [ ] Unit tests for format conversions
- [ ] Integration tests for tool execution
- [ ] Manual testing per provider

### Phase 5: Polish (Week 5)
- [ ] Error handling improvements
- [ ] User documentation
- [ ] Developer documentation

---

## Key API Differences

| Feature | OpenAI | Anthropic | Ollama |
|---------|--------|-----------|--------|
| Tool param name | `parameters` | `input_schema` | `parameters` |
| Response format | `tool_calls` array | `tool_use` content blocks | `tool_calls` array |
| Tool result role | `"tool"` | `"user"` | `"tool"` |

---

## Success Criteria

- ✅ Can use GPT-4, Claude 3.5, and Llama 3.1 interchangeably
- ✅ Warns user if model doesn't support tools
- ✅ No breaking changes to existing configs
- ✅ 90%+ test coverage

---

## Next Action

Start Phase 1: Create `/src/clio/providers/schemas.py` with canonical format definitions.

See `implementation_roadmap.md` section 1.1 for code structure.
