# jarvis/services/ai/router.py
"""AI Request Router — Ollama only"""
from typing import Optional, AsyncIterator
import time
from jarvis.services.ai.base import AIClient, AIResponse, ResponseMetrics
from jarvis.services.ai.config import AIConfig
from jarvis.services.ai.models import get_model, find_vision_model
from jarvis.services.ai.registry import ProviderRegistry
from jarvis.services.ai.exceptions import AIProviderError, ProviderNotAvailableError
from jarvis.utils.logger import get_logger
from jarvis.config import settings

logger = get_logger(__name__)


class AIRouter:
    """Routes AI requests to Ollama"""

    def __init__(self, config: Optional[AIConfig] = None):
        self.config = config or create_ai_config_from_settings(settings)
        self._client_cache: dict[str, AIClient] = {}

    def _get_client(self, model: str) -> AIClient:
        """Get or create Ollama client for a model"""
        if model not in self._client_cache:
            prov_config = self.config.get_provider_config("ollama")
            kwargs = {"timeout": prov_config.timeout}
            if prov_config.base_url:
                kwargs["base_url"] = prov_config.base_url
            self._client_cache[model] = ProviderRegistry.create_client(
                model_id=model, **kwargs
            )
        return self._client_cache[model]

    async def chat(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        **kwargs
    ) -> AIResponse:
        model_id = model or self.config.default_model
        client = self._get_client(model_id)
        start = time.time()
        response = await client.chat(messages, **kwargs)
        response.metrics = ResponseMetrics(latency_ms=(time.time() - start) * 1000)
        return response

    async def chat_stream(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        **kwargs
    ) -> AsyncIterator[str]:
        model_id = model or self.config.default_model
        client = self._get_client(model_id)
        async for token in client.chat_stream(messages):
            yield token

    async def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        system: Optional[str] = None,
        **kwargs
    ) -> AIResponse:
        messages = [{"role": "user", "content": prompt}]
        if system:
            messages.insert(0, {"role": "system", "content": system})
        return await self.chat(messages, model, **kwargs)

    async def vision_analyze(
        self,
        image_data: bytes,
        prompt: str,
        model: Optional[str] = None,
        **kwargs
    ) -> str:
        model_id = model or self.config.default_model
        model_info = get_model(model_id)
        if model_info and not model_info.supports_vision:
            fallback = find_vision_model(model_info.provider)
            if fallback:
                logger.info(f"[Router] vision: {model_id} → {fallback}")
                model_id = fallback

        logger.info(f"[Router] vision: ollama:{model_id}")
        client = self._get_client(model_id)
        result = await client.vision_analyze(image_data, prompt, **kwargs)
        logger.info(f"[Router] vision OK ({len(result)} chars)")
        return result

    async def health_check(self) -> dict:
        model_id = self.config.default_model
        try:
            client = self._get_client(model_id)
            healthy = await client.health_check()
            return {"ollama": {"status": "healthy" if healthy else "unhealthy", "model": model_id}}
        except Exception as e:
            return {"ollama": {"status": "error", "error": str(e)}}

    async def list_models(self, force_refresh: bool = False) -> list[dict]:
        model_id = self.config.default_model
        client = self._get_client(model_id)
        models = await client.list_models(force_refresh=force_refresh)
        for m in models:
            m["provider"] = "ollama"
        return models

    def clear_cache(self):
        self._client_cache.clear()

    async def close(self):
        for client in self._client_cache.values():
            try:
                await client.close()
            except Exception as e:
                logger.warning(f"Failed to close client: {e}")
        self._client_cache.clear()
