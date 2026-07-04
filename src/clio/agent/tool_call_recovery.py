"""Recover tool calls that models emit as literal text instead of structured calls.

Smaller local models (observed live with qwen3-coder via Ollama) sometimes
write the tool call into the message content, e.g.:

    I'll check the git status.

    {"name": "execute_bash", "arguments": {"command": "git status"}}
    </tool_call>

instead of returning a structured tool_calls entry. Without recovery the raw
JSON leaks into the user-visible answer and the action never runs. This module
extracts such calls so the agent can convert them into synthetic structured
calls and run them through the normal execution path (permissions, loop
detection, batching all still apply).

Handled formats:
- Hermes-style <tool_call>{...}</tool_call> blocks (including unbalanced tags)
- ```json fenced blocks containing a tool-call object
- bare {"name": ..., "arguments": {...}} objects in the text

Only objects whose "name" matches a known tool are recovered; anything else is
left in the text untouched.
"""

import json
import re

_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_TAG_RE = re.compile(r"</?tool_call>")
_CANDIDATE_RE = re.compile(r'\{\s*"name"\s*:')


def _parse_candidate(text: str, start: int):
    """Try to JSON-decode an object starting at `start`; None on failure."""
    try:
        obj, end = json.JSONDecoder().raw_decode(text, start)
    except (json.JSONDecodeError, ValueError):
        return None, start
    return obj, end


def _valid_call(obj, known_tools) -> bool:
    if not isinstance(obj, dict):
        return False
    name = obj.get("name")
    if not isinstance(name, str) or name not in known_tools:
        return False
    args = obj.get("arguments", {})
    return isinstance(args, dict)


def extract_text_tool_calls(content: str, known_tools) -> tuple[str, list[dict]]:
    """Extract tool calls embedded as text.

    Returns (cleaned_content, calls) where calls is a list of
    {"name": str, "arguments": dict}. cleaned_content has the recovered JSON
    and any tool_call tags removed. If nothing is recovered, returns the
    original content and [].
    """
    if not content or '"name"' not in content:
        return content, []

    calls: list[dict] = []
    spans: list[tuple[int, int]] = []

    # Fenced blocks first so their braces aren't re-scanned as bare JSON.
    for match in _FENCE_RE.finditer(content):
        obj, _ = _parse_candidate(match.group(1), 0)
        if _valid_call(obj, known_tools):
            calls.append({"name": obj["name"], "arguments": obj.get("arguments", {})})
            spans.append(match.span())

    def in_recovered_span(pos: int) -> bool:
        return any(s <= pos < e for s, e in spans)

    # Bare (or tag-wrapped) JSON objects anywhere in the remaining text.
    for match in _CANDIDATE_RE.finditer(content):
        start = match.start()
        if in_recovered_span(start):
            continue
        obj, end = _parse_candidate(content, start)
        if _valid_call(obj, known_tools):
            calls.append({"name": obj["name"], "arguments": obj.get("arguments", {})})
            spans.append((start, end))

    if not calls:
        return content, []

    # Remove recovered spans (rightmost first so offsets stay valid), then tags.
    cleaned = content
    for start, end in sorted(spans, reverse=True):
        cleaned = cleaned[:start] + cleaned[end:]
    cleaned = _TAG_RE.sub("", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned, calls


def to_structured_tool_calls(calls: list[dict], id_prefix: str) -> list[dict]:
    """Convert extracted calls to OpenAI-format tool_calls entries."""
    return [
        {
            "id": f"{id_prefix}_{i}",
            "type": "function",
            "function": {
                "name": call["name"],
                "arguments": json.dumps(call["arguments"]),
            },
        }
        for i, call in enumerate(calls)
    ]
