"""OpenAI-compatible provider (works with Ollama, OpenWebUI, etc.)."""
from typing import AsyncIterator, Dict, Any, List, Optional
from openai import AsyncOpenAI
import httpx
import json as json_module
import re

from .base import Provider, Message
from .schemas import ToolDefinition, ToolCall, ToolResult
from .capabilities import supports_tools as check_tool_support


# Matches one <function=NAME> ... </function> block (Qwen3-Coder XML tool format).
_XML_FUNCTION_RE = re.compile(r"<function=([^>\s]+)\s*>(.*?)</function>", re.DOTALL)
# Matches one <parameter=KEY> ... </parameter> inside a function block.
_XML_PARAM_RE = re.compile(r"<parameter=([^>\s]+)\s*>(.*?)</parameter>", re.DOTALL)
# Detects the XML tool format at all (cheap pre-check before regex work).
_XML_TOOL_HINT = "<function="


def parse_xml_tool_calls(content: Optional[str]) -> List[Dict[str, Any]]:
    """Parse Qwen3-Coder's XML tool-call format out of a text response.

    Some models (notably Qwen3-Coder via Ollama, when >~5 tools are supplied)
    emit tool calls as XML text in the message content instead of structured
    `tool_calls`, e.g.::

        <function=read_file>
        <parameter=path>README.md</parameter>
        </function>

    This converts those blocks into the same structured shape the OpenAI SDK
    returns, so the rest of the agent can execute them normally. Returns an
    empty list if no XML tool calls are present.
    """
    if not content or _XML_TOOL_HINT not in content:
        return []

    tool_calls: List[Dict[str, Any]] = []
    for i, fmatch in enumerate(_XML_FUNCTION_RE.finditer(content)):
        name = fmatch.group(1).strip()
        body = fmatch.group(2)
        args: Dict[str, Any] = {}
        for pmatch in _XML_PARAM_RE.finditer(body):
            args[pmatch.group(1).strip()] = pmatch.group(2).strip()
        tool_calls.append({
            "id": f"call_xml_{i}",
            "type": "function",
            "function": {
                "name": name,
                "arguments": json_module.dumps(args),
            },
        })
    return tool_calls


def _strip_xml_tool_calls(content: Optional[str]) -> Optional[str]:
    """Remove the XML tool-call blocks (and stray </tool_call> tags) from text."""
    if not content or _XML_TOOL_HINT not in content:
        return content
    cleaned = _XML_FUNCTION_RE.sub("", content)
    cleaned = cleaned.replace("<tool_call>", "").replace("</tool_call>", "")
    cleaned = cleaned.strip()
    return cleaned or None


def _clean_json_envelope(content: str) -> str:
    """Strip ```json fences and <tool_call> wrappers that models add."""
    s = content.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
        s = re.sub(r"\n?```$", "", s).strip()
    s = s.replace("<tool_call>", "").replace("</tool_call>", "").strip()
    return s


def parse_json_tool_calls(content: Optional[str]) -> List[Dict[str, Any]]:
    """Parse JSON-style tool calls some models emit in the message content.

    e.g. Qwen3-Coder Unsloth GGUFs via Ollama emit:
        {"name": "read_file", "arguments": {"path": "README.md"}}
    or a JSON array of such objects. Only the exact {name, arguments} shape is
    treated as a tool call, so ordinary prose/JSON answers aren't misread.
    Returns [] if the content isn't a tool-call payload.
    """
    if not content:
        return []
    s = _clean_json_envelope(content)
    if not (s.startswith("{") or s.startswith("[")):
        return []
    try:
        parsed = json_module.loads(s)
    except (ValueError, TypeError):
        return []

    candidates = parsed if isinstance(parsed, list) else [parsed]
    tool_calls: List[Dict[str, Any]] = []
    for i, obj in enumerate(candidates):
        if not isinstance(obj, dict) or "name" not in obj:
            return []  # not a clean tool-call payload -> treat as normal text
        name = obj.get("name")
        args = obj.get("arguments", obj.get("parameters", {}))
        if not isinstance(name, str):
            return []
        if isinstance(args, str):
            arguments = args  # already a JSON string
        else:
            arguments = json_module.dumps(args if isinstance(args, dict) else {})
        tool_calls.append({
            "id": f"call_json_{i}",
            "type": "function",
            "function": {"name": name, "arguments": arguments},
        })
    return tool_calls


def extract_text_tool_calls(content: Optional[str]):
    """Best-effort recovery of tool calls a model emitted as text.

    Tries the XML format first, then the JSON format. Returns
    (tool_calls, cleaned_content). If nothing is found, returns ([], content).
    """
    xml_calls = parse_xml_tool_calls(content)
    if xml_calls:
        return xml_calls, _strip_xml_tool_calls(content)
    json_calls = parse_json_tool_calls(content)
    if json_calls:
        # The whole content was the tool-call payload; nothing useful remains.
        return json_calls, None
    return [], content


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
                    # Recover tool calls a model emitted as text (XML or JSON).
                    for choice in result.get("choices", []):
                        msg = choice.get("message", {})
                        if not msg.get("tool_calls"):
                            recovered, cleaned = extract_text_tool_calls(msg.get("content"))
                            if recovered:
                                msg["tool_calls"] = recovered
                                msg["content"] = cleaned
                                choice["finish_reason"] = "tool_calls"
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
                    self._build_choice(
                        role=choice.message.role,
                        content=choice.message.content,
                        structured_tool_calls=[
                            {
                                "id": tc.id,
                                "type": tc.type,
                                "function": {
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments
                                }
                            }
                            for tc in (choice.message.tool_calls or [])
                        ] if choice.message.tool_calls else None,
                        finish_reason=choice.finish_reason,
                    )
                    for choice in response.choices
                ],
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                    "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                    "total_tokens": response.usage.total_tokens if response.usage else 0
                } if response.usage else None
            }

    @staticmethod
    def _build_choice(role, content, structured_tool_calls, finish_reason) -> Dict[str, Any]:
        """Build a normalized choice dict, applying the XML tool-call fallback.

        If the model returned structured tool_calls, use them. Otherwise, some
        models (Qwen3-Coder via Ollama with many tools) emit tool calls as XML
        text in the content -- parse those so they still execute, and strip the
        XML out of the visible content.
        """
        tool_calls = structured_tool_calls
        if not tool_calls:
            recovered, cleaned = extract_text_tool_calls(content)
            if recovered:
                tool_calls = recovered
                content = cleaned
                # The model meant to call a tool, reflect that in finish_reason.
                finish_reason = "tool_calls"
        return {
            "message": {
                "role": role or "assistant",
                "content": content,
                "tool_calls": tool_calls,
            },
            "finish_reason": finish_reason,
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
        # Determine provider type based on base_url.
        # Ollama's default port is 11434, so detect it by port as well as name --
        # a remote Ollama host (e.g. http://100.75.184.45:11434/v1) has neither
        # "ollama" nor "localhost" in the URL but is still Ollama.
        base_url = (self.config.get("base_url") or "").lower()
        provider_type = "openai"  # Default to openai
        if self.is_openwebui or "ollama" in base_url or ":11434" in base_url:
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
