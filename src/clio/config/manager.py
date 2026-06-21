import json
from pathlib import Path
from .schema import Config, ProviderConfig

CONFIG_DIR = Path.home() / ".clio"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_CONFIG = {
    "providers": {
        "ollama-local": {
            "type": "openai-compatible",
            "baseURL": "http://localhost:11434/v1",
            "apiKey": "not-needed",
            "headers": None,
            "models": ["llama3.1:8b", "qwen2.5:7b", "mistral:7b"],
            "hostname": "Ollama (local)"
        }
    },
    "defaults": {
        "provider": "ollama-local",
        "model": "llama3.1:8b"
    },
    "preferences": {
        "auto_approve": False,
        "colorblind_mode": False,
        "system_prompt": None,
        "max_recent_conversations": 20,
        "context_window": 16384,
        "theme": "dark",
        "show_thinking": True
    }
}


class ConfigManager:
    def __init__(self, config_path: Path = CONFIG_FILE):
        self.config_path = config_path

    def load(self) -> Config:
        if not self.config_path.exists():
            self._write_default()
        with open(self.config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return Config.model_validate(data)

    def save(self, config: Config) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        data = config.model_dump()
        # Restore camelCase keys for providers
        for pname, pcfg in data.get("providers", {}).items():
            raw = config.providers[pname]
            data["providers"][pname] = {
                "type": raw.type,
                "baseURL": raw.baseURL,
                "apiKey": raw.apiKey,
                "headers": raw.headers,
                "models": raw.models,
                "hostname": raw.hostname,
            }
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def add_provider(self, name: str, provider: ProviderConfig) -> None:
        config = self.load()
        config.providers[name] = provider
        self.save(config)

    def set_default_model(self, provider_name: str, model: str) -> None:
        config = self.load()
        config.defaults.provider = provider_name
        config.defaults.model = model
        self.save(config)

    def _write_default(self) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2)
