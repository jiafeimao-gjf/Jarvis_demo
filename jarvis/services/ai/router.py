# jarvis/services/ai/router.py
"""AI Request Router — model → provider → adapter"""
from typing import Optional, List, AsyncIterator
import time
from jarvis.services.ai.base import AIClient, AIResponse, ResponseMetrics
from jarvis.services.ai.config import AIConfig, ProviderConfig, create_ai_config_from_settings
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

    def _get_client_with_instance(self, instance, model_id: str) -> AIClient:
        """Get or create adapter for a specific ProviderInstance + model.
        Cache key includes instance.id so different instances never share a client."""
        from jarvis.services.ai.instance_config import ProviderInstance
        inst: ProviderInstance = instance
        cache_key = f"{inst.id}:{model_id}"
        if cache_key in self._client_cache:
            return self._client_cache[cache_key]
        kwargs = {"timeout": inst.timeout}
        if inst.base_url:
            kwargs["base_url"] = inst.base_url
        if inst.api_key:
            kwargs["api_key"] = inst.api_key
        client = ProviderRegistry.create_client_for_instance(inst.type, model_id, **kwargs)
        self._client_cache[cache_key] = client
        return client

    # ── Chat ────────────────────────────────────────────────────

    async def chat(
        self, messages: list[dict], model: Optional[str] = None,
        provider: Optional[str] = None, instance=None,
        enable_fallback: Optional[bool] = None,
        conversation_id: Optional[str] = None,
        **kwargs
    ) -> AIResponse:
        """非流式 chat — 接入 LLMCallLogger 记录 body + response."""
        from jarvis.services.ai.call_logger import get_call_logger
        model_id = model or self.config.default_model

        # 决定实际走的 provider (instance 绑定 → 强制用 instance.type)
        if instance is not None:
            client = self._get_client_with_instance(instance, model_id)
            actual_provider = getattr(instance, "type", "") or self.config.default_provider
            actual_provider_protocol = "openai" if actual_provider in ("openai", "minimax") else "anthropic"
        else:
            fallback = enable_fallback if enable_fallback is not None else self.config.enable_fallback
            providers = self._chain(model_id, provider, fallback)
            actual_provider = providers[0] if providers else (provider or self.config.default_provider)
            actual_provider_protocol = "openai" if actual_provider in ("openai", "minimax") else "anthropic"
            client = None

        cl = get_call_logger()
        rec = cl.start_call(
            model=model_id,
            provider=actual_provider,
            provider_protocol=actual_provider_protocol,
            conversation_id=conversation_id,
            source="router.chat",
            request={
                "messages": messages,
                "tools_count": len(kwargs.get("tools") or []),
                "stream": False,
                "max_tokens": kwargs.get("max_tokens"),
                "temperature": kwargs.get("temperature"),
            },
            metadata={"provider_hint": provider},
        )
        # 把 call_id 显式传给 adapter, 不用 ContextVar (避免 async gen finally reset 抛 ValueError)
        kwargs["call_id"] = rec.call_id
        try:
            if instance is not None:
                start = time.time()
                resp = await client.chat(messages, **kwargs)
                resp.metrics = ResponseMetrics(latency_ms=(time.time() - start) * 1000)
            else:
                fallback = enable_fallback if enable_fallback is not None else self.config.enable_fallback
                providers = self._chain(model_id, provider, fallback)

                errors = []
                resp = None
                for prov in providers:
                    try:
                        client = self._get_client(prov, model_id)
                        start = time.time()
                        resp = await client.chat(messages, **kwargs)
                        resp.metrics = ResponseMetrics(latency_ms=(time.time() - start) * 1000)
                        break
                    except AIProviderError as e:
                        logger.warning(f"[Router] chat: {prov} failed — {e}")
                        errors.append(e)
                        continue
                if resp is None:
                    cl.end_call(rec, status="error", error=f"all providers failed: {[str(e) for e in errors]}")
                    raise AllProvidersFailedError(providers, errors)

            cl.end_call(
                rec,
                response={
                    "content": resp.content or "",
                    "thinking": getattr(resp, "thinking", "") or "",
                    "content_blocks": resp.content_blocks or [],
                    "usage": resp.usage.__dict__ if resp.usage else {},
                    "raw": resp.raw,
                    "stop_reason": "",
                },
                status="success",
            )
            return resp
        except Exception as e:
            cl.end_call(rec, status="error", error=str(e))
            raise

    async def chat_stream(
        self, messages: list[dict], model: Optional[str] = None,
        provider: Optional[str] = None, instance=None,
        conversation_id: Optional[str] = None, **kwargs
    ) -> AsyncIterator[str]:
        model_id = model or self.config.default_model
        if instance is not None:
            client = self._get_client_with_instance(instance, model_id)
        else:
            prov = provider or self.config.default_provider
            client = self._get_client(prov, model_id)
        async for token in client.chat_stream(messages):
            yield token

    async def chat_stream_full(
        self, messages: list[dict], model: Optional[str] = None,
        provider: Optional[str] = None, instance=None,
        conversation_id: Optional[str] = None, **kwargs
    ) -> AsyncIterator[dict]:
        """Stream chat with structured events for tool-use detection.

        接入 LLMCallLogger: 累积 text / thinking / tool_use 事件, 流结束时
        一次性把"重建的 response"写入日志. raw HTTP body 由各 adapter 单独记录.
        """
        from jarvis.services.ai.call_logger import get_call_logger

        model_id = model or self.config.default_model
        if instance is not None:
            client = self._get_client_with_instance(instance, model_id)
            actual_provider = getattr(instance, "type", "") or self.config.default_provider
        else:
            prov = provider or self.config.default_provider
            client = self._get_client(prov, model_id)
            actual_provider = prov
        actual_provider_protocol = "openai" if actual_provider in ("openai", "minimax") else "anthropic"

        cl = get_call_logger()
        rec = cl.start_call(
            model=model_id,
            provider=actual_provider,
            provider_protocol=actual_provider_protocol,
            conversation_id=conversation_id,
            source="router.chat_stream_full",
            request={
                "messages": messages,
                "stream": True,
                "max_tokens": kwargs.get("max_tokens"),
                "temperature": kwargs.get("temperature"),
            },
        )
        # ★ call_id 作为参数传给 client, 不再用 ContextVar
        # 一次 chat 会触发多个 LLM 调用 (Phase 1 + Phase 2+ + topic 生成),
        # 每个调用各自的 call_id, 互不干扰 — 通过参数显式传递最可靠.

        # 流式累积状态
        accumulated_text = ""
        accumulated_thinking = ""
        content_blocks: list[dict] = []
        current_tool: Optional[dict] = None
        tool_args_parts: list[str] = []
        raw_finish_reason = ""
        had_error = False
        error_msg = ""
        final_status = "success"
        final_error: Optional[str] = None

        try:
            async for event in client.chat_stream_full(messages, call_id=rec.call_id):
                etype = event.get("type", "")
                if etype == "text":
                    accumulated_text += event.get("content", "")
                elif etype == "thinking":
                    accumulated_thinking += event.get("content", "")
                elif etype == "tool_use_start":
                    current_tool = {
                        "type": "tool_use",
                        "id": event.get("id", ""),
                        "name": event.get("name", ""),
                        "input": {},
                    }
                    tool_args_parts = []
                elif etype == "tool_use_delta":
                    tool_args_parts.append(event.get("partial_json", ""))
                elif etype == "tool_use_end":
                    if current_tool is not None:
                        full = "".join(tool_args_parts)
                        try:
                            import json as _json
                            current_tool["input"] = _json.loads(full) if full else {}
                        except Exception:
                            current_tool["input"] = {}
                        content_blocks.append(current_tool)
                        current_tool = None
                        tool_args_parts = []
                elif etype == "message_delta":
                    raw_finish_reason = event.get("stop_reason", "") or raw_finish_reason
                elif etype == "error":
                    had_error = True
                    error_msg = event.get("content", "unknown stream error")
                    final_status = "error"
                    final_error = error_msg

                yield event

            # 流正常结束 — 补 text block
            if accumulated_text and not any(
                (isinstance(b, dict) and b.get("type") == "text") for b in content_blocks
            ):
                content_blocks.append({"type": "text", "text": accumulated_text})

        except Exception as e:
            final_status = "error"
            final_error = str(e)
            had_error = True
            try:
                yield {"type": "error", "content": str(e)}
            except Exception:
                pass
        finally:
            # ★ 同步写 — 不依赖 asyncio task 调度, 在 finally 里一定执行
            try:
                cl.end_call(
                    rec,
                    response={
                        "content": accumulated_text,
                        "thinking": accumulated_thinking,
                        "content_blocks": content_blocks,
                        "usage": {},
                        "raw": None,
                        "stop_reason": raw_finish_reason,
                    },
                    status=final_status,
                    error=final_error,
                )
            except Exception as e:
                logger.error(f"[Router] end_call failed: {type(e).__name__}: {e}")

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
