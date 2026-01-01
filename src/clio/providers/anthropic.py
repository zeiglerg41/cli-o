"""Anthropic Claude provider."""
from typing import AsyncIterator, Dict, Any, List, Optional
import json

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
        # Convert messages from OpenAI format to Anthropic format
        system_message, anthropic_messages = self._convert_messages_to_anthropic(messages)

        # Build request params
        params = {
            "model": model,
            "messages": anthropic_messages,
            "max_tokens": kwargs.get("max_tokens", 4096),
        }

        if system_message:
            params["system"] = system_message

        if tools:
            # Convert from OpenAI format to Anthropic format
            params["tools"] = self._convert_tools_to_anthropic(tools)

        # Add other kwargs (temperature, etc.)
        for key in ["temperature", "top_p", "top_k"]:
            if key in kwargs:
                params[key] = kwargs[key]

        response = await self.client.messages.create(**params)

        # Normalize to canonical OpenAI-compatible format
        return self._normalize_response(response)

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
        # Convert messages from OpenAI format to Anthropic format
        system_message, anthropic_messages = self._convert_messages_to_anthropic(messages)

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
            # Convert from OpenAI format to Anthropic format
            params["tools"] = self._convert_tools_to_anthropic(tools)

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

    def _convert_messages_to_anthropic(self, messages: List[Message]) -> tuple[Optional[str], List[Dict[str, Any]]]:
        """Convert OpenAI-format messages to Anthropic format.

        Returns:
            Tuple of (system_message, anthropic_messages)
        """
        system_message = None
        anthropic_messages = []

        for msg in messages:
            if msg["role"] == "system":
                # Extract system message (passed separately in Anthropic)
                system_message = msg["content"]

            elif msg["role"] == "tool":
                # Convert tool result: OpenAI uses role="tool", Anthropic uses role="user" with content blocks
                anthropic_messages.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": msg.get("tool_call_id", ""),
                            "content": msg.get("content", "")
                        }
                    ]
                })

            elif msg["role"] == "assistant" and msg.get("tool_calls"):
                # Convert assistant message with tool_calls to content blocks
                content_blocks = []

                # Add text content if present
                if msg.get("content"):
                    content_blocks.append({
                        "type": "text",
                        "text": msg["content"]
                    })

                # Add tool_use blocks (convert from OpenAI format)
                for tool_call in msg["tool_calls"]:
                    # Parse arguments if it's a JSON string
                    arguments = tool_call["function"]["arguments"]
                    if isinstance(arguments, str):
                        try:
                            arguments = json.loads(arguments)
                        except json.JSONDecodeError:
                            arguments = {}

                    content_blocks.append({
                        "type": "tool_use",
                        "id": tool_call["id"],
                        "name": tool_call["function"]["name"],
                        "input": arguments
                    })

                anthropic_messages.append({
                    "role": "assistant",
                    "content": content_blocks
                })

            else:
                # Pass through other messages unchanged
                anthropic_messages.append(msg)

        return system_message, anthropic_messages

    def _convert_tools_to_anthropic(self, tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert tools from OpenAI format to Anthropic format.

        OpenAI format:
            [{"type": "function", "function": {"name": "...", "description": "...", "parameters": {...}}}]

        Anthropic format:
            [{"name": "...", "description": "...", "input_schema": {...}}]
        """
        anthropic_tools = []
        for tool in tools:
            # Handle both OpenAI format and already-converted format
            if "type" in tool and tool["type"] == "function":
                # OpenAI format: {"type": "function", "function": {...}}
                func = tool["function"]
                anthropic_tools.append({
                    "name": func["name"],
                    "description": func.get("description", ""),
                    "input_schema": func.get("parameters", {})
                })
            elif "name" in tool:
                # Already in Anthropic format or ToolDefinition format
                anthropic_tools.append({
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "input_schema": tool.get("parameters", tool.get("input_schema", {}))
                })
        return anthropic_tools

    def _normalize_response(self, anthropic_response) -> Dict[str, Any]:
        """Convert Anthropic response to canonical OpenAI format.

        Anthropic format has direct content blocks, OpenAI has choices array.
        This normalizes to OpenAI format for provider-agnostic agent code.
        """
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

        # Build message object
        message = {
            "role": "assistant",
            "content": content
        }
        if tool_calls:
            message["tool_calls"] = tool_calls

        # Return canonical OpenAI format
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
