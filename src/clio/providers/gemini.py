"""Google Gemini provider."""
import json
from typing import AsyncIterator, Dict, Any, List, Optional

from .base import Provider, Message
from .schemas import ToolDefinition, ToolCall, ToolResult
from .capabilities import supports_tools as check_tool_support


class GeminiProvider(Provider):
    """Provider for Google Gemini API."""

    def __init__(self, config: Dict[str, Any]):
        """Initialize Gemini provider."""
        super().__init__(config)

        try:
            import google.generativeai as genai
        except ImportError:
            raise ImportError(
                "google-generativeai package required for Gemini provider. "
                "Install with: pip install google-generativeai"
            )

        genai.configure(api_key=config.get("api_key"))
        self.genai = genai
        self.config = config

    async def chat(
        self,
        messages: List[Message],
        model: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Send chat completion request.

        Gemini has different message format:
        - System messages are passed as system_instruction parameter
        - Messages have 'parts' instead of 'content'
        - Role is 'model' instead of 'assistant'
        """
        # Extract system message if present
        system_instruction = None
        gemini_messages = []

        for msg in messages:
            if msg["role"] == "system":
                system_instruction = msg["content"]
            elif msg["role"] == "assistant":
                # Convert 'assistant' to 'model' for Gemini
                gemini_messages.append({
                    "role": "model",
                    "parts": [{"text": msg["content"]}]
                })
            elif msg["role"] == "user":
                # Handle both string content and content blocks
                content = msg.get("content", "")
                if isinstance(content, str):
                    gemini_messages.append({
                        "role": "user",
                        "parts": [{"text": content}]
                    })
                else:
                    # Content blocks (for tool results)
                    parts = []
                    for block in content:
                        if block.get("type") == "tool_result":
                            parts.append({
                                "function_response": {
                                    "name": block.get("tool_use_id", "unknown"),
                                    "response": {"result": block.get("content", "")}
                                }
                            })
                        elif isinstance(block, str):
                            parts.append({"text": block})
                    gemini_messages.append({
                        "role": "user",
                        "parts": parts
                    })

        # Create model instance
        model_instance = self.genai.GenerativeModel(
            model_name=model,
            system_instruction=system_instruction,
            tools=self._convert_tools_to_gemini(tools) if tools else None
        )

        # Build generation config
        generation_config = {}
        if "temperature" in kwargs:
            generation_config["temperature"] = kwargs["temperature"]
        if "max_tokens" in kwargs:
            generation_config["max_output_tokens"] = kwargs["max_tokens"]
        if "top_p" in kwargs:
            generation_config["top_p"] = kwargs["top_p"]

        # Generate response
        response = await model_instance.generate_content_async(
            gemini_messages,
            generation_config=generation_config if generation_config else None
        )

        # Normalize to canonical OpenAI format
        return self._normalize_response(response)

    async def stream_chat(
        self,
        messages: List[Message],
        model: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs
    ) -> AsyncIterator[Dict[str, Any]]:
        """Stream chat completion.

        Gemini streaming returns chunks with candidates.
        """
        # Extract system message
        system_instruction = None
        gemini_messages = []

        for msg in messages:
            if msg["role"] == "system":
                system_instruction = msg["content"]
            elif msg["role"] == "assistant":
                gemini_messages.append({
                    "role": "model",
                    "parts": [{"text": msg["content"]}]
                })
            elif msg["role"] == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    gemini_messages.append({
                        "role": "user",
                        "parts": [{"text": content}]
                    })

        # Create model instance
        model_instance = self.genai.GenerativeModel(
            model_name=model,
            system_instruction=system_instruction,
            tools=self._convert_tools_to_gemini(tools) if tools else None
        )

        # Build generation config
        generation_config = {}
        if "temperature" in kwargs:
            generation_config["temperature"] = kwargs["temperature"]
        if "max_tokens" in kwargs:
            generation_config["max_output_tokens"] = kwargs["max_tokens"]

        # Stream response
        response_stream = await model_instance.generate_content_async(
            gemini_messages,
            generation_config=generation_config if generation_config else None,
            stream=True
        )

        async for chunk in response_stream:
            yield {
                "type": "chunk",
                "data": chunk
            }

    def _normalize_response(self, gemini_response) -> Dict[str, Any]:
        """Convert Gemini response to canonical OpenAI format.

        Gemini format has candidates array with parts, OpenAI has choices.
        This normalizes to OpenAI format for provider-agnostic agent code.
        """
        if not gemini_response.candidates:
            # Empty response
            return {
                "choices": [{
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": ""
                    },
                    "finish_reason": "stop"
                }],
                "usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0
                }
            }

        candidate = gemini_response.candidates[0]

        # Extract text parts
        text_parts = []
        tool_calls = []

        for part in candidate.content.parts:
            if hasattr(part, "text"):
                text_parts.append(part.text)
            elif hasattr(part, "function_call"):
                # Extract function call
                fc = part.function_call
                # Gemini doesn't provide IDs, generate one
                call_id = f"call_{hash(fc.name)}_{len(tool_calls)}"
                tool_calls.append({
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": fc.name,
                        "arguments": json.dumps(dict(fc.args))
                    }
                })

        content = "".join(text_parts)

        # Build message object
        message = {
            "role": "assistant",
            "content": content
        }
        if tool_calls:
            message["tool_calls"] = tool_calls

        # Map finish reason
        finish_reason_map = {
            "STOP": "stop",
            "MAX_TOKENS": "length",
            "SAFETY": "content_filter",
            "RECITATION": "content_filter",
            "OTHER": "stop"
        }
        finish_reason = finish_reason_map.get(
            candidate.finish_reason.name if hasattr(candidate, "finish_reason") else "STOP",
            "stop"
        )

        # Extract usage metadata
        usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0
        }
        if hasattr(gemini_response, "usage_metadata"):
            usage = {
                "prompt_tokens": gemini_response.usage_metadata.prompt_token_count,
                "completion_tokens": gemini_response.usage_metadata.candidates_token_count,
                "total_tokens": gemini_response.usage_metadata.total_token_count
            }

        # Return canonical OpenAI format
        return {
            "choices": [{
                "index": 0,
                "message": message,
                "finish_reason": finish_reason
            }],
            "usage": usage,
            "model": model if hasattr(gemini_response, "model_version") else None
        }

    def _convert_tools_to_gemini(self, tools: List[Dict[str, Any]]) -> List:
        """Convert canonical tool definitions to Gemini format.

        Gemini uses FunctionDeclaration objects.
        """
        from google.generativeai.types import FunctionDeclaration

        gemini_tools = []
        for tool in tools:
            # Extract function definition
            if "function" in tool:
                func = tool["function"]
            else:
                func = tool

            # Create FunctionDeclaration
            gemini_tools.append(
                FunctionDeclaration(
                    name=func["name"],
                    description=func.get("description", ""),
                    parameters=func.get("parameters", {})
                )
            )

        return gemini_tools

    async def list_models(self) -> List[str]:
        """List available models.

        Gemini provides an API to list models.
        """
        try:
            models = []
            for model in self.genai.list_models():
                if "generateContent" in model.supported_generation_methods:
                    models.append(model.name.replace("models/", ""))
            return models
        except Exception:
            # Return known models as fallback
            return [
                "gemini-2.0-flash",
                "gemini-2.0-flash-thinking-exp",
                "gemini-1.5-pro",
                "gemini-1.5-flash",
            ]

    def supports_tools(self, model: str) -> bool:
        """Check if model supports tool calling."""
        return check_tool_support("gemini", model)

    def format_tools_for_api(self, tools: List[ToolDefinition]) -> List[Dict[str, Any]]:
        """Convert canonical tools to Gemini format.

        Gemini uses FunctionDeclaration format.
        """
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters
            }
            for tool in tools
        ]

    def parse_tool_calls_from_response(self, response: Dict[str, Any]) -> List[ToolCall]:
        """Extract tool calls from Gemini response.

        Gemini responses have content.parts with function_call objects.
        """
        choices = response.get("choices", [])
        if not choices:
            return []

        message = choices[0].get("message", {})
        tool_calls_data = message.get("tool_calls", [])

        tool_calls = []
        for tc in tool_calls_data:
            function = tc.get("function", {})
            arguments_str = function.get("arguments", "{}")

            # Parse JSON string to dict
            try:
                arguments = json.loads(arguments_str) if isinstance(arguments_str, str) else arguments_str
            except json.JSONDecodeError:
                arguments = {}

            tool_calls.append(
                ToolCall(
                    id=tc.get("id", ""),
                    name=function.get("name", ""),
                    arguments=arguments
                )
            )

        return tool_calls

    def format_tool_result_for_api(self, result: ToolResult) -> Dict[str, Any]:
        """Format tool result as Gemini message.

        Gemini uses role='user' with function_response parts.
        """
        return {
            "role": "user",
            "content": [
                {
                    "type": "function_response",
                    "function_response": {
                        "name": result.tool_call_id,
                        "response": {"result": result.result}
                    }
                }
            ]
        }
