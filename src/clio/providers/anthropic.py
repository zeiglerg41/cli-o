"""Anthropic Claude provider."""
from typing import AsyncIterator, Dict, Any, List, Optional

from .base import Provider, Message
from .schemas import ToolDefinition, ToolCall, ToolResult
from .capabilities import supports_tools as check_tool_support


class AnthropicProvider(Provider):
    """Provider for Anthropic Claude API."""

    def __init__(self, config: Dict[str, Any]):
        """Initialize Anthropic provider."""
        super().__init__(config)

        try:
            from anthropic import AsyncAnthropic
        except ImportError:
            raise ImportError(
                "anthropic package required for Anthropic provider. "
                "Install with: pip install anthropic"
            )

        self.client = AsyncAnthropic(
            api_key=config.get("api_key"),
            base_url=config.get("base_url") if config.get("base_url") else None
        )

    async def chat(
        self,
        messages: List[Message],
        model: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Send chat completion request.

        Anthropic has different message format:
        - System messages are passed separately
        - Tool results are in user messages with content blocks
        """
        # Extract system message if present (Anthropic uses separate parameter)
        system_message = None
        anthropic_messages = []

        for msg in messages:
            if msg["role"] == "system":
                system_message = msg["content"]
            else:
                anthropic_messages.append(msg)

        # Build request params
        params = {
            "model": model,
            "messages": anthropic_messages,
            "max_tokens": kwargs.get("max_tokens", 4096),
        }

        if system_message:
            params["system"] = system_message

        if tools:
            params["tools"] = tools

        # Add other kwargs (temperature, etc.)
        for key in ["temperature", "top_p", "top_k"]:
            if key in kwargs:
                params[key] = kwargs[key]

        response = await self.client.messages.create(**params)

        # Convert to standard dict format
        return {
            "id": response.id,
            "model": response.model,
            "role": response.role,
            "content": [
                {
                    "type": block.type,
                    **({"text": block.text} if hasattr(block, "text") else {}),
                    **({"id": block.id, "name": block.name, "input": block.input}
                       if block.type == "tool_use" else {})
                }
                for block in response.content
            ],
            "stop_reason": response.stop_reason,
            "usage": {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            }
        }

    async def stream_chat(
        self,
        messages: List[Message],
        model: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs
    ) -> AsyncIterator[Dict[str, Any]]:
        """Stream chat completion.

        Anthropic streaming returns events with different types.
        """
        # Extract system message
        system_message = None
        anthropic_messages = []

        for msg in messages:
            if msg["role"] == "system":
                system_message = msg["content"]
            else:
                anthropic_messages.append(msg)

        # Build request params
        params = {
            "model": model,
            "messages": anthropic_messages,
            "max_tokens": kwargs.get("max_tokens", 4096),
            "stream": True,
        }

        if system_message:
            params["system"] = system_message

        if tools:
            params["tools"] = tools

        for key in ["temperature", "top_p", "top_k"]:
            if key in kwargs:
                params[key] = kwargs[key]

        async with self.client.messages.stream(**params) as stream:
            async for event in stream:
                # Convert event to dict
                yield {
                    "type": event.type,
                    "data": event.model_dump() if hasattr(event, "model_dump") else {}
                }

    async def list_models(self) -> List[str]:
        """List available models.

        Anthropic doesn't provide a models endpoint, so return known models.
        """
        return [
            "claude-3-5-sonnet-20241022",
            "claude-3-5-haiku-20241022",
            "claude-3-opus-20240229",
            "claude-3-sonnet-20240229",
            "claude-3-haiku-20240307",
        ]

    def supports_tools(self, model: str) -> bool:
        """Check if model supports tool calling."""
        return check_tool_support("anthropic", model)

    def format_tools_for_api(self, tools: List[ToolDefinition]) -> List[Dict[str, Any]]:
        """Convert canonical tools to Anthropic format.

        Anthropic uses 'input_schema' instead of 'parameters'.
        """
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.parameters,  # Key difference from OpenAI
            }
            for tool in tools
        ]

    def parse_tool_calls_from_response(self, response: Dict[str, Any]) -> List[ToolCall]:
        """Extract tool calls from Anthropic response.

        Anthropic responses have content blocks, filter for type='tool_use'.
        Arguments are already dicts (not JSON strings like OpenAI).
        """
        content = response.get("content", [])
        tool_calls = []

        for block in content:
            if block.get("type") == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block["id"],
                        name=block["name"],
                        arguments=block["input"]  # Already a dict
                    )
                )

        return tool_calls

    def format_tool_result_for_api(self, result: ToolResult) -> Dict[str, Any]:
        """Format tool result as Anthropic message.

        Anthropic uses role='user' with content blocks of type='tool_result'.
        """
        return {
            "role": "user",  # Key difference: Anthropic uses 'user' not 'tool'
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": result.tool_call_id,
                    "content": result.result
                }
            ]
        }
