"""Dynamic model capability resolution.

Replaces the deny-by-default static TOOL_SUPPORT_MATRIX gate with live
provider truth where available, and allow-by-default everywhere else:

1. Ollama servers report per-model capabilities via /api/show
   ("tools" in the capabilities list) — authoritative for local models.
2. The Anthropic Models API (GET /v1/models/{id}) confirms a model exists
   and reports its context window; every currently served Claude model
   supports tool use, so existence implies tool support.
3. The static matrix in capabilities.py remains as an offline fallback.
4. Anything still unknown is ASSUMED to support tools. The agent loop
   downgrades at runtime if the provider rejects the request with a
   tools-not-supported error — so new models work on day one instead of
   shipping broken (the fate of every post-matrix model under the old gate).
"""

import re
from dataclasses import dataclass
from typing import Optional

import httpx

ANTHROPIC_API_ROOT = "https://api.anthropic.com"
ANTHROPIC_VERSION = "2023-06-01"


@dataclass
class ToolSupport:
    supported: bool
    source: str  # "ollama" | "anthropic-api" | "static" | "assumed" | "runtime"


def _ollama_root(base_url: Optional[str]) -> Optional[str]:
    if not base_url:
        return None
    root = base_url.rstrip("/")
    if root.endswith("/v1"):
        root = root[: -len("/v1")]
    return root


async def query_ollama_capabilities(
    model: str, base_url: str, transport: Optional[httpx.AsyncBaseTransport] = None
) -> Optional[list]:
    """The model's capability list from an Ollama server, or None on failure."""
    root = _ollama_root(base_url)
    if not root:
        return None
    try:
        async with httpx.AsyncClient(timeout=3.0, transport=transport) as client:
            resp = await client.post(f"{root}/api/show", json={"model": model})
            if resp.status_code != 200:
                return None
            caps = resp.json().get("capabilities")
            return caps if isinstance(caps, list) else None
    except Exception:
        return None


async def query_anthropic_model(
    model: str, api_key: str, transport: Optional[httpx.AsyncBaseTransport] = None
) -> Optional[dict]:
    """The model object from the Anthropic Models API, or None on any failure.

    A 404 is returned as {"not_found": True} so callers can distinguish
    "model doesn't exist" from "couldn't check".
    """
    if not api_key:
        return None
    try:
        async with httpx.AsyncClient(timeout=5.0, transport=transport) as client:
            resp = await client.get(
                f"{ANTHROPIC_API_ROOT}/v1/models/{model}",
                headers={"x-api-key": api_key, "anthropic-version": ANTHROPIC_VERSION},
            )
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 404:
                return {"not_found": True}
            return None
    except Exception:
        return None


async def resolve_tool_support(
    provider_type: str,
    model: str,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    transport: Optional[httpx.AsyncBaseTransport] = None,
) -> ToolSupport:
    """Resolve whether a model supports tool calling (see module docstring)."""
    # 1. Ollama: authoritative per-model capability list
    if base_url:
        caps = await query_ollama_capabilities(model, base_url, transport=transport)
        if caps is not None:
            return ToolSupport("tools" in caps, "ollama")

    # 2. Anthropic Models API: existence implies tool support
    if provider_type == "anthropic":
        info = await query_anthropic_model(model, api_key, transport=transport)
        if info is not None:
            return ToolSupport(not info.get("not_found"), "anthropic-api")

    # 3. Static matrix as offline fallback (only positive entries are trusted;
    #    absence is NOT evidence of no support)
    from .capabilities import supports_tools
    matrix_provider = "anthropic" if provider_type == "anthropic" else (
        "openai" if provider_type in ("openai", "openai-compatible") else provider_type
    )
    try:
        if supports_tools(matrix_provider, model):
            return ToolSupport(True, "static")
    except Exception:
        pass

    # 4. Allow by default; the runtime downgrade catches genuine rejections
    return ToolSupport(True, "assumed")


_TOOL_REJECTION_PATTERNS = [
    r"does not support tool",
    r"tool.{0,10}(use|call(ing)?s?).{0,15}(is |are )?not support",
    r"(no|not) support(ed)? (for )?tool",
    r"tools? (is|are) not (supported|available|enabled)",
]


def is_tool_rejection_error(error_str: str) -> bool:
    """True if a provider error says the model can't do tool calling.

    Used by the agent loop to downgrade gracefully: strip tools, retry, and
    remember. Deliberately narrow — a tool *execution* failure or a malformed
    tool call must not match, only capability rejections.
    """
    low = (error_str or "").lower()
    return any(re.search(p, low) for p in _TOOL_REJECTION_PATTERNS)
