# jarvis/services/ai/__init__.py
"""AI Module - Multi-Provider AI Client Support"""
from jarvis.services.ai.base import AIClient, AIResponse, TokenUsage, ResponseMetrics
from jarvis.services.ai.models import Provider, ModelInfo, MODELS
from jarvis.services.ai.config import ProviderConfig, AIConfig
from jarvis.services.ai.registry import ProviderRegistry, register_provider
from jarvis.services.ai.router import AIRouter
from jarvis.services.ai.exceptions import (
    AIProviderError,
    ProviderNotAvailableError,
    ModelNotSupportedError,
    RateLimitError,
    AllProvidersFailedError,
)

__all__ = [
    # Base
    "AIClient",
    "AIResponse",
    "TokenUsage",
    "ResponseMetrics",
    # Models
    "Provider",
    "ModelInfo",
    "MODELS",
    # Config
    "ProviderConfig",
    "AIConfig",
    # Registry
    "ProviderRegistry",
    "register_provider",
    # Router
    "AIRouter",
    # Exceptions
    "AIProviderError",
    "ProviderNotAvailableError",
    "ModelNotSupportedError",
    "RateLimitError",
    "AllProvidersFailedError",
]