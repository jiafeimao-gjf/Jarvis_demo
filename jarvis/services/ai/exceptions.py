# jarvis/services/ai/exceptions.py
"""AI Provider Exceptions"""
from typing import Optional, List


class AIProviderError(Exception):
    """Base exception for AI provider errors"""

    def __init__(
        self,
        provider: str,
        message: str,
        details: Optional[dict] = None
    ):
        self.provider = provider
        self.details = details or {}
        super().__init__(f"[{provider}] {message}")


class ProviderNotAvailableError(AIProviderError):
    """Provider is unavailable (network, credentials, etc.)"""
    pass


class ModelNotSupportedError(AIProviderError):
    """Model not available for this provider"""
    pass


class RateLimitError(AIProviderError):
    """Provider rate limit exceeded"""
    pass


class AuthenticationError(AIProviderError):
    """Authentication failed (invalid API key)"""
    pass


class AllProvidersFailedError(Exception):
    """All providers in failover chain have failed"""

    def __init__(self, providers: List[str], errors: List[Exception]):
        self.providers = providers
        self.errors = errors
        error_msgs = [f"{p}: {str(e)}" for p, e in zip(providers, errors)]
        super().__init__(f"All providers failed: {'; '.join(error_msgs)}")