# jarvis/services/ai/router.py
"""AI Request Router with Failover Support"""
from typing import Optional, List, AsyncIterator
import time
from dataclasses import replace
from jarvis.services.ai.base import AIClient, AIResponse, ResponseMetrics
from jarvis.services.ai.config import AIConfig, ProviderConfig
from jarvis.services.ai.models import MODELS, Provider, get_model, find_vision_model
from jarvis.services.ai.registry import ProviderRegistry
from jarvis.services.ai.exceptions import (
    AIProviderError,
    AllProvidersFailedError,
    ProviderNotAvailableError,
    ModelNotSupportedError,
)
from jarvis.utils.logger import get_logger
from jarvis.config import settings

logger = get_logger(__name__)


class AIRouter:
    """Routes AI requests with automatic failover"""

    def __init__(self, config: Optional[AIConfig] = None):
        # Use provided config or create from settings
        self.config = config or create_ai_config_from_settings(settings)
        self._client_cache: dict[str, AIClient] = {}

    def _get_client(self, provider: str, model: str) -> AIClient:
        """Get or create a client for provider/model"""
        cache_key = f"{provider}:{model}"
        if cache_key not in self._client_cache:
            prov_config = self.config.get_provider_config(provider)

            # Provider-specific kwargs
            kwargs = {
                "timeout": prov_config.timeout,
                "max_retries": prov_config.max_retries,
            }

            # Only add base_url for providers that need it (Ollama)
            if provider == "ollama" and prov_config.base_url:
                kwargs["base_url"] = prov_config.base_url

            # Only add api_key for cloud providers
            if provider in ("openai", "anthropic") and prov_config.api_key:
                kwargs["api_key"] = prov_config.api_key

            self._client_cache[cache_key] = ProviderRegistry.create_client(
                model_id=model,
                **kwargs
            )
        return self._client_cache[cache_key]

    async def chat(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        provider: Optional[str] = None,
        enable_fallback: Optional[bool] = None,
        **kwargs
    ) -> AIResponse:
        """Send chat request with optional failover"""
        enable_fallback = enable_fallback if enable_fallback is not None else self.config.enable_fallback
        model_id = model or self.config.default_model
        provider_str = provider or self.config.default_provider

        # Get model info
        model_info = get_model(model_id)

        # Build provider chain
        if enable_fallback:
            providers = self._build_provider_chain(model_id, provider_str)
        else:
            providers = [provider_str]

        # Try each provider
        errors = []
        for prov in providers:
            try:
                client = self._get_client(prov, model_id)
                start = time.time()
                response = await client.chat(messages, **kwargs)
                response.metrics = ResponseMetrics(latency_ms=(time.time() - start) * 1000)
                return response
            except TypeError as e:
                # Handle case where adapter doesn't accept certain params
                logger.warning(f"Provider {prov} doesn't accept some parameters: {e}")
                raise
            except ModelNotSupportedError as e:
                logger.warning(f"Model {model_id} not supported by {prov}: {e}")
                errors.append(e)
                continue
            except AIProviderError as e:
                logger.warning(f"Provider {prov} failed: {e}")
                errors.append(e)
                continue
            except Exception as e:
                logger.error(f"Unexpected error from {prov}: {e}")
                errors.append(e)
                continue

        raise AllProvidersFailedError(providers, errors)

    async def chat_stream(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        provider: Optional[str] = None,
        **kwargs
    ) -> AsyncIterator[str]:
        """Stream chat from primary provider (no failover for streaming)"""
        model_id = model or self.config.default_model
        provider_str = provider or self.config.default_provider

        try:
            client = self._get_client(provider_str, model_id)
            async for token in client.chat_stream(messages):
                yield token
        except AIProviderError as e:
            logger.error(f"Chat stream error: {e}")
            yield f"Error: {str(e)}"

    async def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        system: Optional[str] = None,
        enable_fallback: Optional[bool] = None,
        **kwargs
    ) -> AIResponse:
        """Generate text with optional failover"""
        messages = [{"role": "user", "content": prompt}]
        if system:
            messages.insert(0, {"role": "system", "content": system})

        return await self.chat(messages, model, provider, enable_fallback, **kwargs)

    async def vision_analyze(
        self,
        image_data: bytes,
        prompt: str,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        **kwargs
    ) -> str:
        """Analyze image with vision-capable model"""
        model_id = model or self.config.default_model
        model_info = get_model(model_id)

        # If model doesn't support vision, find a fallback
        if model_info and not model_info.supports_vision:
            provider_enum = Provider(model_info.provider) if model_info else None
            fallback_model = find_vision_model(provider_enum) if provider_enum else None
            if fallback_model:
                logger.info(f"Model {model_id} doesn't support vision, using {fallback_model}")
                model_id = fallback_model

        # Build provider chain for vision
        providers = self._build_provider_chain(model_id, provider)

        errors = []
        for prov in providers:
            try:
                client = self._get_client(prov, model_id)
                return await client.vision_analyze(image_data, prompt, **kwargs)
            except AIProviderError as e:
                logger.warning(f"Vision provider {prov} failed: {e}")
                errors.append(e)
                continue

        raise AllProvidersFailedError(providers, errors)

    def _build_provider_chain(
        self,
        model_id: str,
        preferred_provider: Optional[str]
    ) -> List[str]:
        """Build ordered list of providers to try"""
        chain = []
        model_info = get_model(model_id)

        # Preferred provider first
        if preferred_provider:
            chain.append(preferred_provider)

        # Then model provider
        if model_info and model_info.provider.value not in chain:
            chain.append(model_info.provider.value)

        # Then fallback chain
        for prov in self.config.fallback_chain:
            if prov not in chain:
                chain.append(prov)

        return chain

    async def health_check(self, provider: Optional[str] = None) -> dict:
        """Check health of all or specific provider"""
        result = {}
        providers = [provider] if provider else [p.value for p in Provider]

        for prov in providers:
            try:
                model_id = self.config.get_provider_config(prov).default_model
                client = self._get_client(prov, model_id)
                healthy = await client.health_check()
                result[prov] = {"status": "healthy" if healthy else "unhealthy", "model": model_id}
            except Exception as e:
                result[prov] = {"status": "error", "error": str(e)}

        return result

    async def list_models(self, provider: Optional[str] = None) -> list[dict]:
        """List available models from provider(s)"""
        result = []
        providers = [provider] if provider else [p.value for p in Provider]

        for prov in providers:
            try:
                # Get a default model for the provider to create client
                model_id = self.config.get_provider_config(prov).default_model
                client = self._get_client(prov, model_id)
                models = await client.list_models()
                for m in models:
                    m["provider"] = prov
                result.extend(models)
            except Exception as e:
                logger.warning(f"Failed to list models for {prov}: {e}")

        return result

    def clear_cache(self):
        """Clear client cache"""
        self._client_cache.clear()
        logger.info("AI router client cache cleared")