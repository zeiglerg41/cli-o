"""Base provider interface."""
from abc import ABC, abstractmethod
from typing import AsyncIterator, Dict, Any, List, Optional

from .schemas import ToolDefinition, ToolCall, ToolResult


class Message(dict):
    """Message in conversation."""
    pass


class Provider(ABC):
    """Base provider interface for LLM providers with tool calling support."""

    def __init__(self, config: Dict[str, Any]):
        """Initialize provider with config."""
        self.config = config

    @abstractmethod
    async def chat(
        self,
        messages: List[Message],
        model: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Send chat completion request."""
        pass

    @abstractmethod
    async def stream_chat(
        self,
        messages: List[Message],
        model: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs
    ) -> AsyncIterator[Dict[str, Any]]:
        """Stream chat completion."""
        pass

    @abstractmethod
    async def list_models(self) -> List[str]:
        """List available models."""
        pass

    @abstractmethod
    def supports_tools(self, model: str) -> bool:
        """Check if a model supports tool calling.

        Args:
            model: Model name to check

        Returns:
            True if model supports tool calling, False otherwise

        Example:
            >>> provider.supports_tools("gpt-4o")
            True
        """
        pass

    @abstractmethod
    def format_tools_for_api(self, tools: List[ToolDefinition]) -> Any:
        """Convert canonical tool definitions to provider-specific format.

        Args:
            tools: List of canonical tool definitions

        Returns:
            Provider-specific tool definitions format

        Example:
            OpenAI: [{"type": "function", "function": {...}}, ...]
            Anthropic: [{"name": "...", "input_schema": {...}}, ...]
        """
        pass

    @abstractmethod
    def parse_tool_calls_from_response(self, response: Any) -> List[ToolCall]:
        """Extract tool calls from provider response.

        Args:
            response: Raw provider API response

        Returns:
            List of canonical tool calls (empty if no tool calls)

        Example:
            OpenAI: Extract from response.choices[0].message.tool_calls
            Anthropic: Extract from response.content blocks with type="tool_use"
        """
        pass

    @abstractmethod
    def format_tool_result_for_api(self, result: ToolResult) -> Dict[str, Any]:
        """Format tool result as provider-specific message.

        Args:
            result: Canonical tool result

        Returns:
            Provider-specific message format for tool results

        Example:
            OpenAI: {"role": "tool", "tool_call_id": "...", "content": "..."}
            Anthropic: {"role": "user", "content": [{"type": "tool_result", ...}]}
        """
        pass
