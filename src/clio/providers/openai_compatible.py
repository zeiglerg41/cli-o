"""OpenAI-compatible provider (works with Ollama, OpenWebUI, etc.)."""
from typing import AsyncIterator, Dict, Any, List, Optional
from openai import AsyncOpenAI
import httpx
from .base import Provider, Message


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
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    **self.headers
                }
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    json=params,
                    headers=headers,
                    timeout=120.0
                )
                response.raise_for_status()
                return response.json()
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
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    **self.headers
                }
                async with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    json=params,
                    headers=headers,
                    timeout=120.0
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            data = line[6:]
                            if data == "[DONE]":
                                break
                            import json
                            yield json.loads(data)
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
