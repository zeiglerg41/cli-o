# Provider Abstraction Layer - Implementation Roadmap

This document outlines the step-by-step plan for implementing unified tool calling support across all LLM providers in clio.

## Overview

**Goal**: Create a provider-agnostic abstraction layer that seamlessly handles tool calling across OpenAI, Anthropic, and Ollama with automatic format conversion and capability detection.

**Key Principle**: Single model for everything - the same model handles context understanding, reasoning, and tool calling in a unified agentic loop.

---

## Architecture Design

### Current State
- ✅ Provider abstraction exists (`/src/clio/providers/base.py`)
- ✅ OpenAI-compatible provider implemented
- ✅ Tool definitions in OpenAI format
- ✅ Agentic loop in `Agent.chat()` executes tools
- ⚠️ No Anthropic provider
- ⚠️ No capability detection for tool support

### Target State
- Unified provider interface with tool calling support
- Automatic tool format conversion for each provider
- Response format normalization to canonical format
- Capability detection warns users about unsupported models
- Seamless provider switching mid-conversation

---

## Phase 1: Core Abstraction Layer (Week 1)

### 1.1 Define Canonical Formats

**File**: `/src/clio/providers/schemas.py` (new)

```python
from typing import List, Dict, Any, Optional, Literal
from pydantic import BaseModel

class ToolDefinition(BaseModel):
    """Canonical tool definition format."""
    name: str
    description: str
    parameters: Dict[str, Any]  # JSON Schema

class ToolCall(BaseModel):
    """Canonical tool call format."""
    id: str
    name: str
    arguments: Dict[str, Any]  # Already parsed

class ToolResult(BaseModel):
    """Canonical tool result format."""
    tool_call_id: str
    result: str  # JSON serialized

class Message(BaseModel):
    """Canonical message format."""
    role: Literal["user", "assistant", "system", "tool"]
    content: Optional[str] = None
    tool_calls: Optional[List[ToolCall]] = None
    tool_call_id: Optional[str] = None  # For tool result messages
```

**Tasks**:
- [ ] Create schemas.py with canonical formats
- [ ] Add validation with Pydantic
- [ ] Write unit tests for schema validation

---

### 1.2 Enhance Base Provider Interface

**File**: `/src/clio/providers/base.py` (update)

Add new abstract methods to `Provider` base class:

```python
@abstractmethod
def supports_tools(self, model: str) -> bool:
    """Check if model supports tool calling."""
    pass

@abstractmethod
def format_tools_for_api(self, tools: List[ToolDefinition]) -> Any:
    """Convert canonical tools to provider-specific format."""
    pass

@abstractmethod
def parse_tool_calls_from_response(self, response: Any) -> List[ToolCall]:
    """Extract tool calls from provider response."""
    pass

@abstractmethod
def format_tool_result_for_api(self, result: ToolResult) -> Dict[str, Any]:
    """Format tool result as provider-specific message."""
    pass
```

**Tasks**:
- [ ] Update Provider base class
- [ ] Add docstrings with examples
- [ ] Update OpenAICompatibleProvider to implement new methods

---

### 1.3 Capability Detection Module

**File**: `/src/clio/providers/capabilities.py` (new)

```python
TOOL_SUPPORT_MATRIX = {
    "openai": {
        "gpt-4": True,
        "gpt-4-turbo": True,
        "gpt-4o": True,
        # ... full list
    },
    "anthropic": {
        "claude-3-5-sonnet": True,
        # ... full list
    },
    "ollama": {
        "llama3.1": True,
        "mistral-nemo": True,
        # ... full list
    }
}

def check_tool_support(provider_type: str, model: str) -> bool:
    """Check if a model supports tool calling with prefix matching."""
    # Implementation with prefix matching logic
    pass
```

**Tasks**:
- [ ] Create capabilities.py
- [ ] Populate TOOL_SUPPORT_MATRIX from research
- [ ] Implement prefix matching logic
- [ ] Unit tests for capability detection

---

### 1.4 Update OpenAICompatibleProvider

**File**: `/src/clio/providers/openai_compatible.py` (update)

Implement the new interface methods:

```python
def supports_tools(self, model: str) -> bool:
    return check_tool_support("openai", model)

def format_tools_for_api(self, tools: List[ToolDefinition]) -> List[Dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            }
        }
        for tool in tools
    ]

def parse_tool_calls_from_response(self, response) -> List[ToolCall]:
    if not hasattr(response.choices[0].message, 'tool_calls'):
        return []

    return [
        ToolCall(
            id=tc.id,
            name=tc.function.name,
            arguments=json.loads(tc.function.arguments)
        )
        for tc in response.choices[0].message.tool_calls or []
    ]

def format_tool_result_for_api(self, result: ToolResult) -> Dict:
    return {
        "role": "tool",
        "tool_call_id": result.tool_call_id,
        "content": result.result
    }
```

**Tasks**:
- [ ] Implement new methods
- [ ] Handle edge cases (no tool_calls, invalid JSON)
- [ ] Unit tests for each method

---

## Phase 2: Anthropic Provider (Week 2)

### 2.1 Create AnthropicProvider

**File**: `/src/clio/providers/anthropic.py` (new)

```python
from anthropic import Anthropic
from .base import Provider
from .schemas import ToolDefinition, ToolCall, ToolResult

class AnthropicProvider(Provider):
    def __init__(self, api_key: str, base_url: Optional[str] = None):
        self.client = Anthropic(api_key=api_key)

    def supports_tools(self, model: str) -> bool:
        return check_tool_support("anthropic", model)

    def format_tools_for_api(self, tools: List[ToolDefinition]) -> List[Dict]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.parameters  # Key difference: input_schema
            }
            for tool in tools
        ]

    def parse_tool_calls_from_response(self, response) -> List[ToolCall]:
        tool_calls = []
        for block in response.content:
            if block.type == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.id,
                    name=block.name,
                    arguments=block.input  # Already a dict
                ))
        return tool_calls

    def format_tool_result_for_api(self, result: ToolResult) -> Dict:
        return {
            "role": "user",  # Key difference: role is "user"
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": result.tool_call_id,
                    "content": result.result
                }
            ]
        }

    async def chat(self, messages, model, tools=None, **kwargs):
        # Convert messages to Anthropic format
        # Handle system messages (Anthropic uses separate parameter)
        # Make API call
        # Return normalized response
        pass
```

**Tasks**:
- [ ] Implement AnthropicProvider class
- [ ] Handle message format conversion
- [ ] Handle system messages separately (Anthropic requirement)
- [ ] Add anthropic SDK to dependencies
- [ ] Unit tests for format conversions
- [ ] Integration test with Anthropic API

---

### 2.2 Update Provider Factory

**File**: `/src/clio/providers/__init__.py` (update)

```python
def create_provider(provider_type: str, **config) -> Provider:
    if provider_type == "openai" or provider_type == "ollama":
        return OpenAICompatibleProvider(**config)
    elif provider_type == "anthropic":
        return AnthropicProvider(**config)
    else:
        raise ValueError(f"Unknown provider: {provider_type}")
```

**Tasks**:
- [ ] Add anthropic to factory
- [ ] Update type hints
- [ ] Add provider validation

---

## Phase 3: Agent Integration (Week 3)

### 3.1 Update Agent Tool Handling

**File**: `/src/clio/agent/core.py` (update)

Modify the agentic loop to use new provider interface:

```python
async def chat(self, user_message: str):
    # Before sending tools, check if model supports them
    if self.tools and not self.provider.supports_tools(self.model):
        logger.warning(
            f"Model {self.model} does not support tool calling. "
            f"Tools will be disabled for this conversation."
        )
        # Show warning to user
        self.tools = None

    # Convert tools to canonical format (if not already)
    canonical_tools = [ToolDefinition(**tool) for tool in self.tools]

    # Let provider format tools for its API
    formatted_tools = self.provider.format_tools_for_api(canonical_tools)

    # Make request
    response = await self.provider.chat(
        messages=self.messages,
        model=self.model,
        tools=formatted_tools
    )

    # Parse tool calls using provider
    tool_calls = self.provider.parse_tool_calls_from_response(response)

    # Execute tools
    for tool_call in tool_calls:
        result = await self.execute_tool(tool_call.name, tool_call.arguments)

        # Format result using provider
        tool_result_msg = self.provider.format_tool_result_for_api(
            ToolResult(tool_call_id=tool_call.id, result=result)
        )

        # Add to message history
        self.messages.append(tool_result_msg)
```

**Tasks**:
- [ ] Add tool support checking before requests
- [ ] Add user warnings for unsupported models
- [ ] Update tool execution loop
- [ ] Handle provider-specific message formats
- [ ] Update tests

---

### 3.2 Config Schema Updates

**File**: `/src/clio/config/schema.py` (update)

Add Anthropic provider configuration:

```python
class ProviderConfig(BaseModel):
    type: Literal["openai", "anthropic", "ollama"]
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    # Anthropic-specific
    api_version: Optional[str] = None
```

**Tasks**:
- [ ] Add anthropic provider type
- [ ] Add provider-specific fields
- [ ] Update config validation
- [ ] Migration for existing configs

---

## Phase 4: Testing (Week 4)

### 4.1 Unit Tests

**New File**: `/tests/test_providers/test_tool_calling.py`

```python
def test_openai_tool_format_conversion():
    """Test canonical -> OpenAI tool format."""
    # Test implementation

def test_anthropic_tool_format_conversion():
    """Test canonical -> Anthropic tool format."""
    # Test implementation

def test_openai_response_parsing():
    """Test OpenAI response -> canonical tool calls."""
    # Test implementation

def test_anthropic_response_parsing():
    """Test Anthropic response -> canonical tool calls."""
    # Test implementation

def test_capability_detection():
    """Test model capability detection."""
    # Test known models
    # Test unknown models
    # Test prefix matching
```

**Tasks**:
- [ ] Write unit tests for all format conversions
- [ ] Mock provider responses
- [ ] Test edge cases (empty tool calls, errors)
- [ ] Test capability detection logic

---

### 4.2 Integration Tests

**New File**: `/tests/test_integration/test_tool_execution.py`

```python
@pytest.mark.integration
async def test_openai_tool_execution():
    """Test full tool execution with OpenAI."""
    # Setup mock OpenAI
    # Send request with tools
    # Verify tool execution
    # Verify response

@pytest.mark.integration
async def test_anthropic_tool_execution():
    """Test full tool execution with Anthropic."""
    # Similar structure

@pytest.mark.integration
async def test_provider_switching():
    """Test switching providers mid-conversation."""
    # Start with OpenAI
    # Switch to Anthropic
    # Verify message conversion
```

**Tasks**:
- [ ] Set up test fixtures
- [ ] Mock API responses
- [ ] Test tool execution loop
- [ ] Test error handling
- [ ] Test provider switching

---

### 4.3 Manual Testing Plan

**Checklist for manual testing:**

#### OpenAI Provider
- [ ] GPT-4o: Single tool call (read_file)
- [ ] GPT-4o: Parallel tool calls (read_file + execute_bash)
- [ ] GPT-3.5-turbo: Tool calling
- [ ] Model without tool support: Verify warning

#### Anthropic Provider
- [ ] Claude 3.5 Sonnet: Single tool call
- [ ] Claude 3.5 Sonnet: Response with text + tool_use
- [ ] Claude 3.5 Sonnet: Multi-turn tool usage
- [ ] Claude Haiku: Tool calling

#### Ollama Provider
- [ ] Llama 3.1: Tool calling
- [ ] Model without tool support: Verify warning

#### Cross-Provider
- [ ] Start with OpenAI, switch to Anthropic
- [ ] Start with Anthropic, switch to OpenAI
- [ ] Tool execution errors handled gracefully
- [ ] Network errors handled gracefully

---

## Phase 5: Polish & Documentation (Week 5)

### 5.1 Error Handling

**Tasks**:
- [ ] Add user-friendly error messages
- [ ] Graceful degradation when tools unsupported
- [ ] Better logging for debugging
- [ ] Retry logic for transient failures

---

### 5.2 User Documentation

**New File**: `/docs/user_guide_providers.md`

**Content**:
- Supported providers and models
- How to configure each provider
- Tool calling capabilities per provider
- Switching providers
- Troubleshooting

**Tasks**:
- [ ] Write user guide
- [ ] Add examples for each provider
- [ ] Document limitations

---

### 5.3 Developer Documentation

**New File**: `/docs/dev_guide_adding_providers.md`

**Content**:
- How to add a new provider
- Provider interface reference
- Testing requirements
- Examples

**Tasks**:
- [ ] Write developer guide
- [ ] Document provider interface
- [ ] Provide templates

---

## Success Metrics

### Functionality
- ✅ All providers support tool calling
- ✅ Seamless provider switching
- ✅ Capability detection works correctly
- ✅ Graceful degradation for unsupported models

### Code Quality
- ✅ 90%+ test coverage for new code
- ✅ All type hints correct (mypy passes)
- ✅ No linting errors
- ✅ Documentation complete

### User Experience
- ✅ Clear warnings for unsupported models
- ✅ No breaking changes to existing configs
- ✅ Tool execution feels seamless regardless of provider
- ✅ Error messages are actionable

---

## Dependencies

### New Python Packages
```bash
pip install anthropic  # For Anthropic provider
```

### Development Dependencies
```bash
pip install pytest-asyncio  # For async tests
pip install pytest-mock      # For mocking
pip install responses        # For mocking HTTP
```

---

## Risk Mitigation

### Risk 1: Breaking Changes
**Mitigation**:
- Keep existing OpenAI provider working
- Add feature flags for new providers
- Versioned config schema with migration

### Risk 2: API Changes
**Mitigation**:
- Pin provider SDK versions
- Monitor provider changelogs
- Have fallback logic

### Risk 3: Performance Impact
**Mitigation**:
- Benchmark format conversions
- Cache capability detection results
- Optimize hot paths

---

## Timeline Summary

| Phase | Duration | Deliverables |
|-------|----------|-------------|
| Phase 1 | Week 1 | Core abstractions, schemas, capability detection |
| Phase 2 | Week 2 | Anthropic provider implementation |
| Phase 3 | Week 3 | Agent integration, config updates |
| Phase 4 | Week 4 | Comprehensive testing |
| Phase 5 | Week 5 | Polish, docs, release prep |

**Total**: ~5 weeks for full implementation

---

## Next Steps

1. Review this roadmap
2. Get approval on architecture design
3. Set up development branch
4. Begin Phase 1 implementation
5. Daily check-ins on progress

---

## Questions for Discussion

1. Should we support streaming tool calls initially or defer to later?
2. Should we add telemetry to track provider usage?
3. How should we handle provider-specific features (e.g., Anthropic's beta headers)?
4. Should we add a "test mode" that validates tool execution without API calls?
