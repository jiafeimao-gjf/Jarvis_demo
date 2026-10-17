# tests/test_model_resolution.py
"""未显式指定 model 时的模型解析测试。

回归背景: 语音链路 `_handle_voice_input` → `chat_engine.chat(text, conv_id)`
不传 model, 旧逻辑回退到全局默认 (qwen3:4b), 却通过 active ProviderInstance
(deepseek) 的 adapter 发出, 导致:
  "The supported API model names are deepseek-flash, deepseek-v4-pro,
   but you passed qwen3:4b." → HTTP 400
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

from jarvis.services.ai.base import AIResponse
from jarvis.services.ai.instance_config import ProviderInstance
from jarvis.services.ai.router import AIRouter, _resolve_model_id


def _config(default_model="qwen3:4b"):
    return SimpleNamespace(default_model=default_model)


def _instance(default_model="deepseek-v4-pro"):
    return ProviderInstance(
        id="deepseek",
        type="anthropic",
        display_name="deepseek",
        base_url="https://api.deepseek.com/anthropic",
        api_key="test-key",
        default_model=default_model,
    )


class TestRouterModelId:
    def test_explicit_model_wins(self):
        assert _resolve_model_id("my-model", _instance(), _config()) == "my-model"

    def test_instance_default_beats_global_default(self):
        assert _resolve_model_id(None, _instance(), _config()) == "deepseek-v4-pro"

    def test_global_default_without_instance(self):
        assert _resolve_model_id(None, None, _config()) == "qwen3:4b"

    def test_empty_instance_model_falls_back_to_global(self):
        assert _resolve_model_id(None, _instance(default_model=""), _config()) == "qwen3:4b"


class TestChatEngineModel:
    def test_chat_engine_resolution_matches_router(self):
        from jarvis.core.chat_engine import ChatEngine

        inst = _instance()
        assert ChatEngine._resolve_model("explicit", inst) == "explicit"
        assert ChatEngine._resolve_model(None, inst) == "deepseek-v4-pro"
        assert ChatEngine._resolve_model(None, None) is None
        assert ChatEngine._resolve_model(None, _instance(default_model="")) is None


class TestRouterChatUsesInstanceModel:
    def test_chat_without_model_uses_instance_default(self, monkeypatch):
        """走 instance 时, 未传 model 必须用 instance.default_model 建 client。"""
        router = AIRouter()
        inst = _instance()
        captured = {}

        class FakeClient:
            async def chat(self, messages, **kwargs):
                return AIResponse(content="ok", model="deepseek-v4-pro", provider="anthropic")

        def fake_get_client_with_instance(instance, model_id):
            captured["model_id"] = model_id
            captured["instance_id"] = instance.id
            return FakeClient()

        monkeypatch.setattr(
            router, "_get_client_with_instance", fake_get_client_with_instance
        )

        # 避免真实写 LLM 调用日志
        import jarvis.services.ai.call_logger as call_logger_module

        class FakeCallLogger:
            def start_call(self, **kwargs):
                return SimpleNamespace(call_id="test-call")

            def end_call(self, *args, **kwargs):
                return None

        monkeypatch.setattr(
            call_logger_module, "get_call_logger", lambda: FakeCallLogger()
        )

        asyncio.run(router.chat([{"role": "user", "content": "hi"}], instance=inst))

        assert captured["instance_id"] == "deepseek"
        assert captured["model_id"] == "deepseek-v4-pro"
