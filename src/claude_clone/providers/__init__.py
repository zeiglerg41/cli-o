"""Provider factory and exports."""
from typing import Dict, Any
from .base import Provider, Message
from .openai_compatible import OpenAICompatibleProvider


def create_provider(provider_type: str, config: Dict[str, Any]) -> Provider:
    """Create provider instance based on type."""
    if provider_type == "openai-compatible":
        return OpenAICompatibleProvider(config)
    elif provider_type == "openai":
        # OpenAI is also OpenAI-compatible, just with different base URL
        if "base_url" not in config:
            config["base_url"] = "https://api.openai.com/v1"
        return OpenAICompatibleProvider(config)
    elif provider_type == "anthropic":
        # TODO: Implement Anthropic provider
        raise NotImplementedError("Anthropic provider not yet implemented")
    else:
        raise ValueError(f"Unknown provider type: {provider_type}")


__all__ = ["Provider", "Message", "create_provider"]
