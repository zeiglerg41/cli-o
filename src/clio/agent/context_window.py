"""Best-effort resolution of a model's context window size.

Resolution order:
1. Explicit per-model override in the provider config (context_windows map).
2. The Ollama API (/api/show) when the provider points at an Ollama server:
   a baked-in num_ctx parameter wins, else the model's maximum context length.
3. A prefix table of known model families.
4. DEFAULT_CONTEXT_WINDOW.

Note the Ollama value can overstate the effective runtime window: the server's
OLLAMA_CONTEXT_LENGTH default is not exposed via the API, so a model reporting
a 256k maximum may actually be running with less. Use a config override when
the server is configured below the model maximum.
"""

import re
from typing import Optional

import httpx

DEFAULT_CONTEXT_WINDOW = 32768

# Prefix table, most specific first. First match wins.
KNOWN_CONTEXT_WINDOWS: list[tuple[str, int]] = [
    ("qwen3-coder", 262144),
    ("qwen3", 40960),
    ("qwen2.5-coder", 32768),
    ("qwen2.5", 32768),
    ("devstral", 131072),
    ("mistral-nemo", 128000),
    ("mistral", 32768),
    ("llama3.1", 131072),
    ("llama3.2", 131072),
    ("llama3", 8192),
    ("gpt-4o", 128000),
    ("gpt-4.1", 1047576),
    ("gpt-4-turbo", 128000),
    ("gpt-4", 8192),
    ("gpt-3.5", 16385),
    ("o1", 200000),
    ("o3", 200000),
    ("claude", 200000),
    ("gemini-1.5-pro", 2097152),
    ("gemini", 1048576),
    ("deepseek", 65536),
    ("grok", 131072),
]


def lookup_known_window(model: str) -> Optional[int]:
    """Match a model name against the known-families prefix table."""
    name = model.lower()
    # Strip a registry/namespace prefix like "library/" or "unsloth/"
    if "/" in name:
        name = name.rsplit("/", 1)[-1]
    for prefix, size in KNOWN_CONTEXT_WINDOWS:
        if name.startswith(prefix):
            return size
    return None


def _ollama_root(base_url: str) -> Optional[str]:
    """Return the Ollama server root for an OpenAI-compatible base_url, or None."""
    if not base_url:
        return None
    root = base_url.rstrip("/")
    if root.endswith("/v1"):
        root = root[: -len("/v1")]
    return root


async def query_ollama_context_window(model: str, base_url: str) -> Optional[int]:
    """Ask an Ollama server for the model's context size; None on any failure.

    Prefers the RUNTIME context of the loaded model (/api/ps context_length),
    which reflects what the server actually allocated; falls back to a
    baked-in num_ctx parameter, else the architecture's maximum from
    /api/show model_info (which can overstate the effective window).
    """
    root = _ollama_root(base_url)
    if not root:
        return None
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            ps = await client.get(f"{root}/api/ps")
            if ps.status_code == 200:
                for loaded in (ps.json().get("models") or []):
                    if loaded.get("model") == model or loaded.get("name") == model:
                        ctx = loaded.get("context_length")
                        if isinstance(ctx, int) and ctx > 0:
                            return ctx
            resp = await client.post(f"{root}/api/show", json={"model": model})
            if resp.status_code != 200:
                return None
            data = resp.json()
    except Exception:
        return None

    params = data.get("parameters") or ""
    match = re.search(r"^num_ctx\s+(\d+)", params, re.MULTILINE)
    if match:
        return int(match.group(1))

    model_info = data.get("model_info") or {}
    for key, value in model_info.items():
        if key.endswith(".context_length") and isinstance(value, int):
            return value
    return None


async def get_context_window(
    model: str,
    base_url: Optional[str] = None,
    override: Optional[int] = None,
    provider_type: Optional[str] = None,
    api_key: Optional[str] = None,
) -> int:
    """Resolve the context window for a model (see module docstring for order)."""
    if override:
        return override
    from_ollama = await query_ollama_context_window(model, base_url) if base_url else None
    if from_ollama:
        return from_ollama
    if provider_type == "anthropic" and api_key:
        from ..providers.model_catalog import query_anthropic_model
        info = await query_anthropic_model(model, api_key)
        if info and isinstance(info.get("max_input_tokens"), int):
            return info["max_input_tokens"]
    return lookup_known_window(model) or DEFAULT_CONTEXT_WINDOW
