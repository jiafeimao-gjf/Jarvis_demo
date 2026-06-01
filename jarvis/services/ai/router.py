# jarvis/services/ai/router.py
"""AI Request Router — model → provider → adapter"""
from typing import Optional, List, AsyncIterator
import time
from jarvis.services.ai.base import AIClient, AIResponse, ResponseMetrics
from jarvis.services.ai.config import AIConfig, ProviderConfig
from jarvis.services.ai.models import MODELS, Provider, get_model, find_vision_model
from jarvis.services.ai.registry import ProviderRegistry
from jarvis.services.ai.exceptions import (
    AIProviderError, AllProvidersFailedError, ProviderNotAvailableError,
)
from jarvis.utils.logger import get_logger
from jarvis.config import settings

logger = get_logger(__name__)


class AIRouter:
    """Routes AI requests: model ID → provider → adapter → API call"""

    def __init__(self, config: Optional[AIConfig] = None):
        self.config = config or create_ai_config_from_settings(settings)
        self._client_cache: dict[str, AIClient] = {}

    # ── Client factory ──────────────────────────────────────────

    def _get_client(self, provider: str, model: str) -> AIClient:
        """Get or create adapter for provider+model"""
        cache_key = f"{provider}:{model}"
        if cache_key not in self._client_cache:
            prov_config = self.config.get_provider_config(provider)
            kwargs = {"timeout": prov_config.timeout}
            if prov_config.base_url:
                kwargs["base_url"] = prov_config.base_url
            if prov_config.api_key:
                kwargs["api_key"] = prov_config.api_key
            self._client_cache[cache_key] = ProviderRegistry.create_client(
                model_id=model, **kwargs
            )
        return self._client_cache[cache_key]

    # ── Chat ────────────────────────────────────────────────────

    async def chat(
        self, messages: list[dict], model: Optional[str] = None,
        provider: Optional[str] = None, enable_fallback: Optional[bool] = None,
        **kwargs
    ) -> AIResponse:
        model_id = model or self.config.default_model
        fallback = enable_fallback if enable_fallback is not None else self.config.enable_fallback
        providers = self._chain(model_id, provider, fallback)

        errors = []
        for prov in providers:
            try:
                client = self._get_client(prov, model_id)
                start = time.time()
                resp = await client.chat(messages, **kwargs)
                resp.metrics = ResponseMetrics(latency_ms=(time.time() - start) * 1000)
                return resp
            except AIProviderError as e:
                logger.warning(f"[Router] chat: {prov} failed — {e}")
                errors.append(e)
                continue
        raise AllProvidersFailedError(providers, errors)

    async def chat_stream(
        self, messages: list[dict], model: Optional[str] = None,
        provider: Optional[str] = None, **kwargs
    ) -> AsyncIterator[str]:
        model_id = model or self.config.default_model
        prov = provider or self.config.default_provider
        client = self._get_client(prov, model_id)
        async for token in client.chat_stream(messages):
            yield token

    async def chat_stream_full(
        self, messages: list[dict], model: Optional[str] = None,
        provider: Optional[str] = None, **kwargs
    ) -> AsyncIterator[dict]:
        """Stream chat with structured events for tool-use detection."""
        model_id = model or self.config.default_model
        prov = provider or self.config.default_provider
        client = self._get_client(prov, model_id)
        async for event in client.chat_stream_full(messages):
            yield event

    async def generate(
        self, prompt: str, model: Optional[str] = None,
        system: Optional[str] = None, **kwargs
    ) -> AIResponse:
        messages = [{"role": "user", "content": prompt}]
        if system:
            messages.insert(0, {"role": "system", "content": system})
        return await self.chat(messages, model, **kwargs)

    # ── Vision ──────────────────────────────────────────────────

    async def vision_analyze(
        self, image_data: bytes, prompt: str,
        model: Optional[str] = None, provider: Optional[str] = None, **kwargs
    ) -> str:
        model_id = model or self.config.default_model
        model_info = get_model(model_id)
        if model_info and not model_info.supports_vision:
            fallback = find_vision_model(model_info.provider)
            if fallback:
                model_id = fallback
                model_info = get_model(model_id)

        providers = self._chain(model_id, provider)
        errors = []
        for prov in providers:
            try:
                prov_model = model_id
                if model_info and model_info.provider.value != prov:
                    fb = find_vision_model(Provider(prov))
                    if not fb:
                        continue
                    prov_model = fb
                    model_info = get_model(prov_model)
                client = self._get_client(prov, prov_model)
                result = await client.vision_analyze(image_data, prompt, **kwargs)
                return result
            except AIProviderError as e:
                errors.append(e)
                continue
        raise AllProvidersFailedError(providers, errors)

    # ── Helpers ─────────────────────────────────────────────────

    def _chain(self, model_id: str, preferred: Optional[str] = None,
               fallback: bool = True) -> List[str]:
        """Build ordered list of providers"""
        chain = []
        model_info = get_model(model_id)
        if preferred:
            chain.append(preferred)
        if model_info and model_info.provider.value not in chain:
            chain.append(model_info.provider.value)
        if fallback:
            for prov in self.config.fallback_chain:
                if prov not in chain:
                    chain.append(prov)
        return chain

    async def health_check(self) -> dict:
        result = {}
        for prov in ["ollama"]:
            prov_config = self.config.get_provider_config(prov)
            if not prov_config.enabled:
                continue
            try:
                client = self._get_client(prov, prov_config.default_model)
                healthy = await client.health_check()
                result[prov] = {"status": "healthy" if healthy else "unhealthy"}
            except Exception as e:
                result[prov] = {"status": "error", "error": str(e)}
        return result

    async def list_models(self, force_refresh: bool = False) -> list[dict]:
        result = []
        for prov_name in ["ollama"]:
            prov_config = self.config.get_provider_config(prov_name)
            if not prov_config.enabled:
                continue
            try:
                client = self._get_client(prov_name, prov_config.default_model)
                models = await client.list_models(force_refresh=force_refresh)
                for m in models:
                    m["provider"] = prov_name
                result.extend(models)
            except Exception as e:
                logger.warning(f"Failed to list models for {prov_name}: {e}")
        return result

    def clear_cache(self):
        self._client_cache.clear()

    async def close(self):
        for client in self._client_cache.values():
            try:
                await client.close()
            except Exception as e:
                logger.warning(f"Failed to close client: {e}")
        self._client_cache.clear()
