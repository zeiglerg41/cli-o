"""Canonical schemas for provider-agnostic tool calling.

These schemas define the internal representation of tools, tool calls, and messages
that all providers convert to/from their specific formats.
"""

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class ToolDefinition(BaseModel):
    """Canonical tool definition format.

    All providers convert their tool definitions to/from this format.

    Example:
        {
            "name": "get_weather",
            "description": "Get current weather for a location",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {"type": "string", "description": "City name"}
                },
                "required": ["location"]
            }
        }
    """
    name: str = Field(..., description="Tool function name")
    description: str = Field(..., description="What the tool does")
    parameters: Dict[str, Any] = Field(..., description="JSON Schema for parameters")


class ToolCall(BaseModel):
    """Canonical tool call format.

    Represents a request from the model to execute a tool.
    Arguments are already parsed from JSON.

    Example:
        {
            "id": "call_abc123",
            "name": "get_weather",
            "arguments": {"location": "San Francisco"}
        }
    """
    id: str = Field(..., description="Unique identifier for this tool call")
    name: str = Field(..., description="Name of the tool to call")
    arguments: Dict[str, Any] = Field(..., description="Tool arguments (already parsed)")


class ToolResult(BaseModel):
    """Canonical tool result format.

    Represents the result of executing a tool, to be sent back to the model.

    Example:
        {
            "tool_call_id": "call_abc123",
            "result": '{"temperature": 72, "condition": "sunny"}'
        }
    """
    tool_call_id: str = Field(..., description="ID of the tool call this is responding to")
    result: str = Field(..., description="JSON-serialized result of tool execution")


class Message(BaseModel):
    """Canonical message format.

    Internal representation of messages that works across all providers.

    Examples:
        User message:
            {"role": "user", "content": "Hello"}

        Assistant text message:
            {"role": "assistant", "content": "Hi there!"}

        Assistant with tool calls:
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "call_123", "name": "get_weather", "arguments": {...}}
                ]
            }

        Tool result message:
            {
                "role": "tool",
                "content": '{"result": "data"}',
                "tool_call_id": "call_123"
            }
    """
    role: Literal["user", "assistant", "system", "tool"] = Field(
        ..., description="Message role"
    )
    content: Optional[str] = Field(
        None, description="Text content of the message"
    )
    tool_calls: Optional[List[ToolCall]] = Field(
        None, description="Tool calls requested by assistant (assistant role only)"
    )
    tool_call_id: Optional[str] = Field(
        None, description="ID of tool call being responded to (tool role only)"
    )
