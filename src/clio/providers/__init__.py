"""Provider factory and exports."""
from typing import Dict, Any
from .base import Provider, Message
from .openai_compatible import OpenAICompatibleProvider
from .anthropic import AnthropicProvider


def create_provider(provider_type: str, config: Dict[str, Any]) -> Provider:
    """Create provider instance based on type.

    Args:
        provider_type: Type of provider ("openai", "openai-compatible", "anthropic")
        config: Provider configuration dict

    Returns:
        Provider instance

    Raises:
        ValueError: If provider_type is unknown
    """
    if provider_type == "openai-compatible":
        return OpenAICompatibleProvider(config)
    elif provider_type == "openai":
        # OpenAI is also OpenAI-compatible, just with different base URL
        if "base_url" not in config:
            config["base_url"] = "https://api.openai.com/v1"
        return OpenAICompatibleProvider(config)
    elif provider_type == "anthropic":
        return AnthropicProvider(config)
    else:
        raise ValueError(f"Unknown provider type: {provider_type}")


__all__ = ["Provider", "Message", "create_provider"]
