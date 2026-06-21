from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field


class ProviderConfig(BaseModel):
    type: str = "openai-compatible"
    baseURL: Optional[str] = Field(None, alias="base_url")
    apiKey: Optional[str] = Field(None, alias="api_key")
    headers: Optional[Dict[str, str]] = None
    models: List[str] = []
    hostname: Optional[str] = None

    model_config = {"populate_by_name": True}


class Defaults(BaseModel):
    provider: str = "ollama-local"
    model: str = "llama3.1:8b"


class Preferences(BaseModel):
    auto_approve: bool = False
    colorblind_mode: bool = False
    system_prompt: Optional[str] = None
    max_recent_conversations: int = 20
    context_window: int = 16384
    theme: str = "dark"
    show_thinking: bool = True


class Config(BaseModel):
    providers: Dict[str, ProviderConfig] = {}
    defaults: Defaults = Field(default_factory=Defaults)
    preferences: Preferences = Field(default_factory=Preferences)
