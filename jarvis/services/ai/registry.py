# jarvis/services/ai/registry.py
"""Provider Registry for AI Clients"""
from typing import Dict, Type, Optional, List, Callable
from jarvis.services.ai.base import AIClient
from jarvis.services.ai.models import Provider, ModelInfo, MODELS
from jarvis.utils.logger import get_logger

logger = get_logger(__name__)


def register_provider(provider: Provider) -> Callable:
    """Decorator to register a provider adapter"""
    def decorator(cls: Type[AIClient]) -> Type[AIClient]:
        ProviderRegistry.register(provider, cls)
        return cls
    return decorator


class ProviderRegistry:
    """Central registry for AI providers"""

    _providers: Dict[Provider, Type[AIClient]] = {}
    _config_cache: Dict[Provider, dict] = {}

    @classmethod
    def register(cls, provider: Provider, adapter_class: Type[AIClient]):
        """Register an AI provider adapter"""
        cls._providers[provider] = adapter_class
        logger.info(f"Registered AI provider: {provider.value}")

    @classmethod
    def configure(cls, provider: Provider, config: dict):
        """Configure a provider with settings"""
        cls._config_cache[provider] = config
        logger.info(f"Configured AI provider: {provider.value}")

    @classmethod
    def create_client(
        cls,
        model_id: str,
        provider: Optional[str] = None,
        **kwargs
    ) -> AIClient:
        """Create an AI client for a specific model"""
        model_info = MODELS.get(model_id)
        if not model_info:
            available = list(MODELS.keys())
            raise ValueError(f"Unknown model: {model_id}. Available: {available}")

        adapter_class = cls._providers.get(model_info.provider)
        if not adapter_class:
            raise ValueError(f"No adapter registered for provider: {model_info.provider}")

        # Merge config cache with kwargs
        config = cls._config_cache.get(model_info.provider, {})
        config.update(kwargs)

        # Strip kwargs that don't apply to this provider (e.g. use_minimax
        # passed by AIRouter fallback chain; it only makes sense for
        # AnthropicAdapter/MiniMax)
        if model_info.provider not in (Provider.ANTHROPIC, Provider.MINIMAX):
            config.pop("use_minimax", None)
        if model_info.provider not in (Provider.OPENAI, Provider.ANTHROPIC, Provider.MINIMAX):
            config.pop("api_key", None)

        return adapter_class(model=model_info.model_id, **config)

    @classmethod
    def list_providers(cls) -> List[Provider]:
        """List all registered providers"""
        return list(cls._providers.keys())

    @classmethod
    def list_models(cls, provider: Optional[Provider] = None) -> List[str]:
        """List available models, optionally filtered by provider"""
        if provider:
            return [mid for mid, mi in MODELS.items() if mi.provider == provider]
        return list(MODELS.keys())

    @classmethod
    def get_model_info(cls, model_id: str) -> Optional[ModelInfo]:
        """Get model information"""
        return MODELS.get(model_id)