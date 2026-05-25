# jarvis/services/ai/config.py
"""AI Configuration for Multi-Provider Support"""
from dataclasses import dataclass, field
from typing import Optional, List
from jarvis.services.ai.models import MODELS, Provider


@dataclass
class ProviderConfig:
    """Configuration for a single AI provider"""
    enabled: bool = True
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    default_model: str = "qwen3:4b"
    timeout: float = 60.0
    max_retries: int = 3


@dataclass
class AIConfig:
    """Global AI configuration"""
    default_provider: str = "ollama"
    default_model: str = "qwen3:4b"

    # Provider-specific configs
    ollama: ProviderConfig = field(
        default_factory=lambda: ProviderConfig(
            base_url="http://localhost:11434",
            default_model="qwen3:4b"
        )
    )
    openai: ProviderConfig = field(default_factory=ProviderConfig)
    anthropic: ProviderConfig = field(default_factory=ProviderConfig)

    # Fallback settings
    fallback_chain: List[str] = field(
        default_factory=lambda: ["ollama", "openai", "anthropic"]
    )
    enable_fallback: bool = True

    # Request settings
    request_timeout: float = 60.0
    max_retries: int = 3

    def get_provider_config(self, provider: str) -> ProviderConfig:
        """Get config for a specific provider"""
        return getattr(self, provider.lower(), ProviderConfig())

    def resolve_model(self, model_id: Optional[str]) -> str:
        """Resolve model ID with fallback to default"""
        if model_id and model_id in MODELS:
            return model_id
        return self.default_model

    def resolve_provider(self, provider: Optional[str]) -> str:
        """Resolve provider with fallback to default"""
        if provider:
            return provider
        return self.default_provider