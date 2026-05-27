# jarvis/services/ai/config.py
"""AI Configuration for Multi-Provider Support"""
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from jarvis.config import OllamaConfig, OpenAIConfig, AnthropicConfig, MiniMaxConfig
from jarvis.services.ai.models import MODELS, Provider


@dataclass
class ProviderConfig:
    """Configuration for a single AI provider"""
    enabled: bool = True
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    default_model: str = "qwen3:4b"
    timeout: float = 60.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "base_url": self.base_url,
            "default_model": self.default_model,
            "timeout": self.timeout,
            "has_api_key": bool(self.api_key)
        }


@dataclass
class AIConfig:
    """Global AI configuration - 从 jarvis.config 导入"""
    default_provider: str = "ollama"
    default_model: str = "qwen3:4b"

    # Provider-specific configs
    ollama: ProviderConfig = field(default_factory=lambda: ProviderConfig(
        base_url="http://localhost:11434",
        default_model="qwen3:4b"
    ))
    openai: ProviderConfig = field(default_factory=ProviderConfig)
    anthropic: ProviderConfig = field(default_factory=ProviderConfig)
    minimax: ProviderConfig = field(default_factory=ProviderConfig)

    # Fallback settings
    fallback_chain: List[str] = field(
        default_factory=lambda: ["ollama", "openai", "anthropic", "minimax"]
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

    def to_dict(self) -> Dict[str, Any]:
        """Export config as dict"""
        return {
            "default_provider": self.default_provider,
            "default_model": self.default_model,
            "enable_fallback": self.enable_fallback,
            "fallback_chain": self.fallback_chain,
            "providers": {
                "ollama": self.ollama.to_dict(),
                "openai": self.openai.to_dict(),
                "anthropic": self.anthropic.to_dict(),
            }
        }


def create_ai_config_from_settings(settings) -> AIConfig:
    """从全局 settings 创建 AIConfig"""
    config = AIConfig()

    # Ollama
    config.ollama = ProviderConfig(
        enabled=True,
        base_url=settings.ai.ollama.base_url,
        default_model=settings.ai.ollama.model,
        timeout=settings.ai.ollama.timeout,
        max_retries=settings.ai.ollama.max_retries,
    )

    # OpenAI
    config.openai = ProviderConfig(
        enabled=bool(settings.ai.openai.api_key),
        base_url=settings.ai.openai.base_url,
        api_key=settings.ai.openai.api_key,
        default_model=settings.ai.openai.model,
        timeout=settings.ai.openai.timeout,
    )

    # Anthropic
    config.anthropic = ProviderConfig(
        enabled=bool(settings.ai.anthropic.api_key),
        base_url=settings.ai.anthropic.base_url,
        api_key=settings.ai.anthropic.api_key,
        default_model=settings.ai.anthropic.model,
        timeout=settings.ai.anthropic.timeout,
    )

    # MiniMax
    config.minimax = ProviderConfig(
        enabled=bool(settings.ai.minimax.api_key),
        base_url=settings.ai.minimax.base_url,
        api_key=settings.ai.minimax.api_key,
        default_model=settings.ai.minimax.model,
        timeout=settings.ai.minimax.timeout,
    )

    config.default_provider = settings.ai.default_provider
    config.default_model = settings.ai.default_model
    config.enable_fallback = settings.ai.enable_fallback
    config.fallback_chain = settings.ai.fallback_chain

    return config