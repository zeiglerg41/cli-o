"""OpenAI-compatible provider (works with Ollama, OpenWebUI, etc.)."""
from typing import AsyncIterator, Dict, Any, List, Optional
from openai import AsyncOpenAI
import httpx
import json as json_module

from .base import Provider, Message
from .schemas import ToolDefinition, ToolCall, ToolResult
from .capabilities import supports_tools as check_tool_support


class OpenAICompatibleProvider(Provider):
    """Provider for OpenAI-compatible APIs."""
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize OpenAI-compatible provider."""
        super().__init__(config)

        base_url = config.get("base_url", "")
        self.api_key = config.get("api_key", "not-needed")
        self.headers = config.get("headers") or {}  # Ensure it's never None

        # Check if this is OpenWebUI (uses /api/chat not /api/v1/chat)
        if "/api" in base_url and not base_url.endswith("/v1"):
            self.is_openwebui = True
            self.base_url = base_url
            self.client = None  # We'll use httpx directly
        else:
            self.is_openwebui = False
            # Use OpenAI SDK for standard endpoints
            self.client = AsyncOpenAI(
                base_url=base_url,
                api_key=self.api_key,
                default_headers=self.headers
            )

    def _build_headers(self) -> Dict[str, str]:
        """Build HTTP headers for OpenWebUI requests."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            **self.headers
        }

    async def chat(
        self,
        messages: List[Message],
        model: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Send chat completion request."""
        params = {
            "model": model,
            "messages": messages,
            **kwargs
        }

        if tools:
            params["tools"] = tools

        # Use httpx for OpenWebUI, OpenAI SDK for others
        if self.is_openwebui:
            async with httpx.AsyncClient() as client:
                try:
                    response = await client.post(
                        f"{self.base_url}/chat/completions",
                        json=params,
                        headers=self._build_headers(),
                        timeout=300.0  # 5 minutes for larger models
                    )
                    response.raise_for_status()
                    result = response.json()
                    return result
                except httpx.TimeoutException as e:
                    raise Exception(f"API request timed out after 300s: {str(e)}")
                except httpx.HTTPStatusError as e:
                    raise Exception(f"API returned error {e.response.status_code}: {e.response.text}")
                except Exception as e:
                    raise Exception(f"API request failed: {str(e)}")
        else:
            response = await self.client.chat.completions.create(**params)

            # Convert to dict
            return {
                "id": response.id,
                "model": response.model,
                "choices": [
                    {
                        "message": {
                            "role": choice.message.role,
                            "content": choice.message.content,
                            "tool_calls": [
                                {
                                    "id": tc.id,
                                    "type": tc.type,
                                    "function": {
                                        "name": tc.function.name,
                                        "arguments": tc.function.arguments
                                    }
                                }
                                for tc in (choice.message.tool_calls or [])
                            ] if choice.message.tool_calls else None
                        },
                        "finish_reason": choice.finish_reason
                    }
                    for choice in response.choices
                ],
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                    "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                    "total_tokens": response.usage.total_tokens if response.usage else 0
                } if response.usage else None
            }
    
    async def stream_chat(
        self,
        messages: List[Message],
        model: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs
    ) -> AsyncIterator[Dict[str, Any]]:
        """Stream chat completion."""
        params = {
            "model": model,
            "messages": messages,
            "stream": True,
            **kwargs
        }

        if tools:
            params["tools"] = tools

        # Use httpx for OpenWebUI, OpenAI SDK for others
        if self.is_openwebui:
            async with httpx.AsyncClient() as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    json=params,
                    headers=self._build_headers(),
                    timeout=120.0
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            data = line[6:]
                            if data == "[DONE]":
                                break
                            yield json_module.loads(data)
        else:
            stream = await self.client.chat.completions.create(**params)

            async for chunk in stream:
                yield {
                    "id": chunk.id,
                    "model": chunk.model,
                    "choices": [
                        {
                            "delta": {
                                "role": choice.delta.role if choice.delta.role else None,
                                "content": choice.delta.content if choice.delta.content else None,
                                "tool_calls": choice.delta.tool_calls if choice.delta.tool_calls else None
                            },
                            "finish_reason": choice.finish_reason
                        }
                        for choice in chunk.choices
                    ]
                }
    
    async def list_models(self) -> List[str]:
        """List available models."""
        # Return models from config since not all APIs support listing
        return self.config.get("models", [])

    def supports_tools(self, model: str) -> bool:
        """Check if model supports tool calling.

        Uses capability detection for OpenAI/Ollama models.
        """
        # Determine provider type based on base_url
        provider_type = "openai"  # Default to openai
        if self.is_openwebui or "ollama" in self.config.get("base_url", "").lower():
            provider_type = "ollama"

        return check_tool_support(provider_type, model)

    def format_tools_for_api(self, tools: List[ToolDefinition]) -> List[Dict[str, Any]]:
        """Convert canonical tools to OpenAI format.

        OpenAI format wraps tool definition in {"type": "function", "function": {...}}
        """
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

    def parse_tool_calls_from_response(self, response: Dict[str, Any]) -> List[ToolCall]:
        """Extract tool calls from OpenAI response.

        OpenAI responses have tool_calls in message.tool_calls array.
        Arguments are JSON strings that need to be parsed.
        """
        if not response.get("choices"):
            return []

        message = response["choices"][0].get("message", {})
        tool_calls_raw = message.get("tool_calls")

        if not tool_calls_raw:
            return []

        tool_calls = []
        for tc in tool_calls_raw:
            try:
                # Parse arguments from JSON string
                arguments = json_module.loads(tc["function"]["arguments"])
            except (json_module.JSONDecodeError, KeyError) as e:
                # If parsing fails, use empty dict
                arguments = {}

            tool_calls.append(
                ToolCall(
                    id=tc["id"],
                    name=tc["function"]["name"],
                    arguments=arguments
                )
            )

        return tool_calls

    def format_tool_result_for_api(self, result: ToolResult) -> Dict[str, Any]:
        """Format tool result as OpenAI message.

        OpenAI uses role="tool" with tool_call_id field.
        """
        return {
            "role": "tool",
            "tool_call_id": result.tool_call_id,
            "content": result.result
        }
