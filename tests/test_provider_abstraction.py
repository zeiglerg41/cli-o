"""Unit tests for provider abstraction layer and tool calling support."""
import pytest
import json
from src.clio.providers.schemas import ToolDefinition, ToolCall, ToolResult
from src.clio.providers.capabilities import supports_tools, get_supported_models
from src.clio.providers.openai_compatible import OpenAICompatibleProvider
from src.clio.providers.anthropic import AnthropicProvider


class TestCanonicalSchemas:
    """Test canonical schema models."""

    def test_tool_definition_creation(self):
        """Test creating a tool definition."""
        tool = ToolDefinition(
            name="get_weather",
            description="Get weather for location",
            parameters={
                "type": "object",
                "properties": {
                    "location": {"type": "string"}
                },
                "required": ["location"]
            }
        )
        assert tool.name == "get_weather"
        assert tool.description == "Get weather for location"
        assert "location" in tool.parameters["properties"]

    def test_tool_call_creation(self):
        """Test creating a tool call."""
        tool_call = ToolCall(
            id="call_123",
            name="get_weather",
            arguments={"location": "San Francisco"}
        )
        assert tool_call.id == "call_123"
        assert tool_call.name == "get_weather"
        assert tool_call.arguments["location"] == "San Francisco"

    def test_tool_result_creation(self):
        """Test creating a tool result."""
        result = ToolResult(
            tool_call_id="call_123",
            result='{"temperature": 72}'
        )
        assert result.tool_call_id == "call_123"
        assert "temperature" in result.result


class TestCapabilityDetection:
    """Test capability detection for tool calling support."""

    def test_openai_gpt4_supports_tools(self):
        """Test that GPT-4 supports tools."""
        assert supports_tools("openai", "gpt-4") is True
        assert supports_tools("openai", "gpt-4o") is True
        assert supports_tools("openai", "gpt-4-turbo") is True

    def test_openai_gpt4_variant_supports_tools(self):
        """Test that GPT-4 variants support tools (prefix matching)."""
        assert supports_tools("openai", "gpt-4-turbo-2024-04-09") is True
        assert supports_tools("openai", "gpt-4o-2024-05-13") is True

    def test_openai_gpt35_supports_tools(self):
        """Test that GPT-3.5-turbo supports tools."""
        assert supports_tools("openai", "gpt-3.5-turbo") is True
        assert supports_tools("openai", "gpt-3.5-turbo-0613") is True

    def test_openai_unknown_model_no_tools(self):
        """Test that unknown OpenAI models don't support tools."""
        assert supports_tools("openai", "gpt-3") is False
        assert supports_tools("openai", "unknown-model") is False

    def test_anthropic_claude_supports_tools(self):
        """Test that Claude models support tools."""
        assert supports_tools("anthropic", "claude-3-5-sonnet-20241022") is True
        assert supports_tools("anthropic", "claude-3-opus") is True
        assert supports_tools("anthropic", "claude-3-haiku") is True

    def test_anthropic_claude_variant_supports_tools(self):
        """Test that Claude variants support tools (prefix matching)."""
        assert supports_tools("anthropic", "claude-3-5-sonnet-20241022") is True
        assert supports_tools("anthropic", "claude-3-opus-20240229") is True

    def test_ollama_llama_supports_tools(self):
        """Test that Llama 3.1 supports tools."""
        assert supports_tools("ollama", "llama3.1") is True
        assert supports_tools("ollama", "llama3.1:8b") is True

    def test_ollama_unknown_model_no_tools(self):
        """Test that unknown Ollama models don't support tools."""
        assert supports_tools("ollama", "llama2") is False
        assert supports_tools("ollama", "unknown") is False

    def test_unknown_provider_no_tools(self):
        """Test that unknown providers don't support tools."""
        assert supports_tools("unknown", "any-model") is False

    def test_case_insensitive_matching(self):
        """Test that model name matching is case insensitive."""
        assert supports_tools("openai", "GPT-4") is True
        assert supports_tools("openai", "Gpt-4o") is True
        assert supports_tools("anthropic", "CLAUDE-3-5-SONNET") is True

    def test_get_supported_models(self):
        """Test getting list of supported models."""
        openai_models = get_supported_models("openai")
        assert "gpt-4" in openai_models
        assert "gpt-4o" in openai_models

        anthropic_models = get_supported_models("anthropic")
        assert "claude-3-5-sonnet" in anthropic_models

        ollama_models = get_supported_models("ollama")
        assert "llama3.1" in ollama_models


class TestOpenAIProviderToolMethods:
    """Test OpenAI provider tool-related methods."""

    def setup_method(self):
        """Set up test fixtures."""
        self.provider = OpenAICompatibleProvider({
            "base_url": "https://api.openai.com/v1",
            "api_key": "test-key"
        })

    def test_supports_tools(self):
        """Test supports_tools method."""
        assert self.provider.supports_tools("gpt-4o") is True
        assert self.provider.supports_tools("gpt-3") is False

    def test_format_tools_for_api(self):
        """Test formatting tools for OpenAI API."""
        tools = [
            ToolDefinition(
                name="get_weather",
                description="Get weather",
                parameters={"type": "object", "properties": {}}
            )
        ]

        formatted = self.provider.format_tools_for_api(tools)

        assert len(formatted) == 1
        assert formatted[0]["type"] == "function"
        assert formatted[0]["function"]["name"] == "get_weather"
        assert formatted[0]["function"]["description"] == "Get weather"

    def test_parse_tool_calls_from_response(self):
        """Test parsing tool calls from OpenAI response."""
        response = {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_123",
                            "type": "function",
                            "function": {
                                "name": "get_weather",
                                "arguments": '{"location": "SF"}'
                            }
                        }
                    ]
                }
            }]
        }

        tool_calls = self.provider.parse_tool_calls_from_response(response)

        assert len(tool_calls) == 1
        assert tool_calls[0].id == "call_123"
        assert tool_calls[0].name == "get_weather"
        assert tool_calls[0].arguments == {"location": "SF"}

    def test_parse_tool_calls_empty_response(self):
        """Test parsing tool calls from response with no tool calls."""
        response = {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": "Hello",
                    "tool_calls": None
                }
            }]
        }

        tool_calls = self.provider.parse_tool_calls_from_response(response)
        assert len(tool_calls) == 0

    def test_parse_tool_calls_invalid_json(self):
        """Test parsing tool calls with invalid JSON arguments."""
        response = {
            "choices": [{
                "message": {
                    "tool_calls": [
                        {
                            "id": "call_123",
                            "function": {
                                "name": "get_weather",
                                "arguments": "invalid json"
                            }
                        }
                    ]
                }
            }]
        }

        tool_calls = self.provider.parse_tool_calls_from_response(response)

        # Should handle gracefully with empty dict
        assert len(tool_calls) == 1
        assert tool_calls[0].arguments == {}

    def test_format_tool_result_for_api(self):
        """Test formatting tool result for OpenAI API."""
        result = ToolResult(
            tool_call_id="call_123",
            result='{"temperature": 72}'
        )

        formatted = self.provider.format_tool_result_for_api(result)

        assert formatted["role"] == "tool"
        assert formatted["tool_call_id"] == "call_123"
        assert formatted["content"] == '{"temperature": 72}'


class TestAnthropicProviderToolMethods:
    """Test Anthropic provider tool-related methods."""

    def setup_method(self):
        """Set up test fixtures."""
        # Mock Anthropic provider (without actual API key)
        self.provider = AnthropicProvider.__new__(AnthropicProvider)
        self.provider.config = {"api_key": "test-key"}

    def test_supports_tools(self):
        """Test supports_tools method."""
        assert self.provider.supports_tools("claude-3-5-sonnet-20241022") is True
        assert self.provider.supports_tools("unknown-model") is False

    def test_format_tools_for_api(self):
        """Test formatting tools for Anthropic API."""
        tools = [
            ToolDefinition(
                name="get_weather",
                description="Get weather",
                parameters={"type": "object", "properties": {}}
            )
        ]

        formatted = self.provider.format_tools_for_api(tools)

        assert len(formatted) == 1
        assert formatted[0]["name"] == "get_weather"
        assert formatted[0]["description"] == "Get weather"
        assert "input_schema" in formatted[0]  # Anthropic uses input_schema
        assert "parameters" not in formatted[0]  # Not "parameters"

    def test_parse_tool_calls_from_response(self):
        """Test parsing tool calls from Anthropic response."""
        response = {
            "content": [
                {
                    "type": "text",
                    "text": "I'll check the weather."
                },
                {
                    "type": "tool_use",
                    "id": "toolu_123",
                    "name": "get_weather",
                    "input": {"location": "SF"}  # Already a dict, not JSON string
                }
            ]
        }

        tool_calls = self.provider.parse_tool_calls_from_response(response)

        assert len(tool_calls) == 1
        assert tool_calls[0].id == "toolu_123"
        assert tool_calls[0].name == "get_weather"
        assert tool_calls[0].arguments == {"location": "SF"}

    def test_parse_tool_calls_text_only_response(self):
        """Test parsing tool calls from text-only response."""
        response = {
            "content": [
                {
                    "type": "text",
                    "text": "Hello"
                }
            ]
        }

        tool_calls = self.provider.parse_tool_calls_from_response(response)
        assert len(tool_calls) == 0

    def test_format_tool_result_for_api(self):
        """Test formatting tool result for Anthropic API."""
        result = ToolResult(
            tool_call_id="toolu_123",
            result='{"temperature": 72}'
        )

        formatted = self.provider.format_tool_result_for_api(result)

        assert formatted["role"] == "user"  # Anthropic uses "user" not "tool"
        assert len(formatted["content"]) == 1
        assert formatted["content"][0]["type"] == "tool_result"
        assert formatted["content"][0]["tool_use_id"] == "toolu_123"
        assert formatted["content"][0]["content"] == '{"temperature": 72}'


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
