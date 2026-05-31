# jarvis/services/ai/config.py
"""AI Configuration — Ollama only"""
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from jarvis.services.ai.models import MODELS


@dataclass
class ProviderConfig:
    """Configuration for Ollama provider"""
    enabled: bool = True
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    default_model: str = "qwen3:4b"
    timeout: float = 60.0
    max_retries: int = 3

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "base_url": self.base_url,
            "default_model": self.default_model,
            "timeout": self.timeout,
        }


@dataclass
class AIConfig:
    """Global AI configuration"""
    default_provider: str = "ollama"
    default_model: str = "qwen3:4b"
    ollama: ProviderConfig = field(default_factory=lambda: ProviderConfig(
        base_url="http://localhost:11434", default_model="qwen3:4b"
    ))
    fallback_chain: List[str] = field(default_factory=lambda: ["ollama"])
    enable_fallback: bool = False
    request_timeout: float = 60.0
    max_retries: int = 3

    def get_provider_config(self, provider: str) -> ProviderConfig:
        return getattr(self, provider.lower(), ProviderConfig())

    def resolve_model(self, model_id: Optional[str]) -> str:
        if model_id and model_id in MODELS:
            return model_id
        return self.default_model

    def resolve_provider(self, provider: Optional[str]) -> str:
        return provider or self.default_provider

    def to_dict(self) -> Dict[str, Any]:
        return {
            "default_provider": self.default_provider,
            "default_model": self.default_model,
            "providers": {"ollama": self.ollama.to_dict()},
        }


def create_ai_config_from_settings(settings) -> AIConfig:
    """Create AIConfig from global settings"""
    config = AIConfig()
    config.ollama = ProviderConfig(
        enabled=True,
        base_url=settings.ai.ollama.base_url,
        default_model=settings.ai.ollama.model,
        timeout=settings.ai.ollama.timeout,
        max_retries=settings.ai.ollama.max_retries,
    )
    config.default_provider = settings.ai.default_provider
    config.default_model = settings.ai.default_model
    config.enable_fallback = settings.ai.enable_fallback
    config.fallback_chain = settings.ai.fallback_chain
    return config
