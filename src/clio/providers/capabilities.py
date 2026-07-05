"""Provider capability detection for tool calling support.

This module tracks which models support tool calling across different providers.
"""

from typing import Dict, Set

# Tool calling support matrix
# Models are lowercase for case-insensitive matching
TOOL_SUPPORT_MATRIX: Dict[str, Dict[str, bool]] = {
    "openai": {
        # GPT-5 family
        "gpt-5.2": True,
        "gpt-5.1": True,
        "gpt-5": True,

        # GPT-4.1 family
        "gpt-4.1": True,
        "gpt-4.1-mini": True,
        "gpt-4.1-nano": True,

        # GPT-4 family
        "gpt-4": True,
        "gpt-4-turbo": True,
        "gpt-4-turbo-preview": True,
        "gpt-4o": True,
        "gpt-4o-mini": True,

        # GPT-3.5 family (0613+)
        "gpt-3.5-turbo": True,
        "gpt-3.5-turbo-0613": True,
        "gpt-3.5-turbo-1106": True,
        "gpt-3.5-turbo-0125": True,

        # o1 models (limited support)
        "o1": True,
        "o1-preview": True,
        "o1-mini": True,
        "o3": True,
        "o3-mini": True,
        "o4-mini": True,
    },
    "anthropic": {
        # Claude 5 family / current frontier. Offline fallback only — live
        # resolution via the Models API in model_catalog.py is preferred.
        "claude-fable-5": True,
        "claude-opus-4-8": True,
        "claude-opus-4-7": True,
        "claude-opus-4-6": True,
        "claude-sonnet-5": True,
        "claude-sonnet-4-6": True,

        # Claude 4.5 family
        "claude-opus-4-5": True,
        "claude-opus-4-5-20251101": True,
        "claude-sonnet-4-5": True,
        "claude-sonnet-4-5-20250929": True,
        "claude-haiku-4-5": True,
        "claude-haiku-4-5-20251001": True,

        # Claude 3.7 family
        "claude-3-7-sonnet": True,
        "claude-3-7-sonnet-20250219": True,

        # Claude 3.5 family
        "claude-3-5-sonnet": True,
        "claude-3-5-sonnet-20241022": True,
        "claude-3-5-haiku": True,
        "claude-3-5-haiku-20241022": True,

        # Claude 3 family
        "claude-3-opus": True,
        "claude-3-opus-20240229": True,
        "claude-3-sonnet": True,
        "claude-3-sonnet-20240229": True,
        "claude-3-haiku": True,
        "claude-3-haiku-20240307": True,
    },
    "ollama": {
        # Open source models with tool support.
        # Keys are matched by prefix, so "qwen3" also matches custom builds
        # like "qwen3-8b-clio" and tagged variants like "qwen3:8b".
        "llama3.1": True,
        "llama3.2": True,
        "llama3.3": True,
        "llama4": True,
        # Qwen family (2, 2.5, 3, and QwQ all support tool calling)
        "qwen2": True,
        "qwen2.5": True,
        "qwen2.5-coder": True,
        "qwen3": True,
        "qwq": True,
        # Mistral family (incl. agentic coding/reasoning variants)
        "mistral": True,
        "mistral-nemo": True,
        "mistral-small": True,
        "mixtral": True,
        "devstral": True,
        "magistral": True,
        # Others
        "firefunction-v2": True,
        "command-r-plus": True,
        "command-r": True,
    },
    "gemini": {
        # Gemini 2.0 family
        "gemini-2.0-flash": True,
        "gemini-2.0-flash-exp": True,
        "gemini-2.0-flash-thinking-exp": True,

        # Gemini 1.5 family
        "gemini-1.5-pro": True,
        "gemini-1.5-pro-exp": True,
        "gemini-1.5-flash": True,
        "gemini-1.5-flash-8b": True,
    }
}


def supports_tools(provider: str, model: str) -> bool:
    """Check if a model supports tool calling.

    Uses exact matching and prefix matching to handle model variants
    (e.g., "gpt-4-turbo-2024-04-09" matches "gpt-4-turbo").

    Args:
        provider: Provider type ("openai", "anthropic", "ollama")
        model: Model name to check

    Returns:
        True if model supports tool calling, False otherwise

    Examples:
        >>> supports_tools("openai", "gpt-4o")
        True
        >>> supports_tools("openai", "gpt-4o-2024-05-13")
        True
        >>> supports_tools("openai", "gpt-3.5")
        False
        >>> supports_tools("anthropic", "claude-3-5-sonnet-20241022")
        True
        >>> supports_tools("ollama", "llama2")
        False
    """
    provider_lower = provider.lower()

    if provider_lower not in TOOL_SUPPORT_MATRIX:
        return False

    model_lower = model.lower()
    supported_models = TOOL_SUPPORT_MATRIX[provider_lower]

    # Exact match
    if model_lower in supported_models:
        return supported_models[model_lower]

    # Prefix match (e.g., "gpt-4-turbo-2024-04-09" matches "gpt-4-turbo")
    for supported_model in supported_models:
        if model_lower.startswith(supported_model):
            return supported_models[supported_model]

    return False


def get_supported_models(provider: str) -> Set[str]:
    """Get set of model prefixes that support tools for a provider.

    Args:
        provider: Provider type ("openai", "anthropic", "ollama")

    Returns:
        Set of supported model name prefixes

    Example:
        >>> sorted(list(get_supported_models("openai")))[:3]
        ['gpt-3.5-turbo', 'gpt-4', 'gpt-4-turbo']
    """
    provider_lower = provider.lower()

    if provider_lower not in TOOL_SUPPORT_MATRIX:
        return set()

    return {
        model
        for model, supported in TOOL_SUPPORT_MATRIX[provider_lower].items()
        if supported
    }
