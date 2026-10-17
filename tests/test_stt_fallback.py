# tests/test_stt_fallback.py
"""STT backend 解析 / 回退 测试。

回归背景: 默认 stt_backend="paraformer", 但 funasr 未安装时
`ParaformerSTT._load()` 抛 ModuleNotFoundError, 异常在
`sub_model_processor.process_audio` 被吞掉 → 返回空字符串 → 前端静默无反应。
whisper 后端本可胜任, 但 get_stt_engine 从未实现文档承诺的回退。
"""
import logging

import pytest
from unittest.mock import MagicMock

from jarvis.services import stt as stt_mod


@pytest.fixture(autouse=True)
def _reset_singleton():
    stt_mod.reset_stt_engine()
    yield
    stt_mod.reset_stt_engine()


class TestBackendResolution:
    def test_paraformer_missing_falls_back_to_whisper(self, monkeypatch):
        """funasr 缺失时, 请求 paraformer 应拿到 whisper 引擎而不是抛异常。"""
        monkeypatch.setattr(stt_mod, "_module_available", lambda name: name != "funasr")

        engine = stt_mod.get_stt_engine("paraformer", ollama_client=MagicMock())

        assert engine.backend_name() == "whisper"

    def test_paraformer_used_when_funasr_present(self, monkeypatch):
        """funasr 可用时不应回退。"""
        monkeypatch.setattr(stt_mod, "_module_available", lambda name: True)

        engine = stt_mod.get_stt_engine("paraformer", ollama_client=MagicMock())

        assert engine.backend_name() == "paraformer"

    def test_resolve_backend_is_pure(self, monkeypatch):
        monkeypatch.setattr(stt_mod, "_module_available", lambda name: name != "funasr")

        assert stt_mod.resolve_backend("paraformer") == "whisper"
        assert stt_mod.resolve_backend("whisper") == "whisper"

    def test_explicit_whisper_untouched(self, monkeypatch):
        monkeypatch.setattr(stt_mod, "_module_available", lambda name: True)

        engine = stt_mod.get_stt_engine("whisper", ollama_client=MagicMock())

        assert engine.backend_name() == "whisper"

    def test_unknown_backend_still_rejected(self):
        with pytest.raises(ValueError, match="Unknown STT backend"):
            stt_mod.get_stt_engine("nonsense", ollama_client=MagicMock())


class TestDegradedEnvironment:
    def test_both_missing_raises_actionable_error(self, monkeypatch):
        """两个后端都不可用时, 报错信息必须点明缺哪个包, 不能是空话。"""
        monkeypatch.setattr(stt_mod, "_module_available", lambda name: False)

        with pytest.raises(RuntimeError, match="funasr"):
            stt_mod.get_stt_engine("paraformer", ollama_client=MagicMock())

    def test_whisper_without_client_raises(self, monkeypatch):
        monkeypatch.setattr(stt_mod, "_module_available", lambda name: True)

        with pytest.raises(ValueError, match="ollama_client"):
            stt_mod.get_stt_engine("whisper", ollama_client=None)


class TestCaching:
    def test_fallback_engine_is_cached(self, monkeypatch):
        """回退后必须复用同一实例, 不能每次调用都重建。"""
        monkeypatch.setattr(stt_mod, "_module_available", lambda name: name != "funasr")
        client = MagicMock()

        first = stt_mod.get_stt_engine("paraformer", ollama_client=client)
        second = stt_mod.get_stt_engine("paraformer", ollama_client=client)

        assert first is second

    def test_switching_backend_rebuilds(self, monkeypatch):
        monkeypatch.setattr(stt_mod, "_module_available", lambda name: True)
        client = MagicMock()

        para = stt_mod.get_stt_engine("paraformer", ollama_client=client)
        whis = stt_mod.get_stt_engine("whisper", ollama_client=client)

        assert para is not whis
        assert para.backend_name() == "paraformer"
        assert whis.backend_name() == "whisper"


class TestStatusReporting:
    def test_status_reports_effective_backend(self, monkeypatch):
        monkeypatch.setattr(stt_mod, "_module_available", lambda name: name != "funasr")

        status = stt_mod.get_stt_status()

        assert status["paraformer_available"] is False
        assert status["whisper_available"] is True
        assert status["effective_backend"] == "whisper"

    def test_status_polling_does_not_spam_warning(self, monkeypatch, caplog):
        """/api/status 每分钟轮询，状态查询不应每次刷一条回退 warning。"""
        monkeypatch.setattr(stt_mod, "_module_available", lambda name: name != "funasr")

        with caplog.at_level(logging.WARNING, logger="jarvis.services.stt"):
            stt_mod.get_stt_status()
            stt_mod.get_stt_status()

        assert not [r for r in caplog.records if "回退" in r.getMessage()]

    def test_real_engine_creation_still_warns(self, monkeypatch, caplog):
        """真正创建引擎时仍要留下回退 warning（可诊断性）。"""
        monkeypatch.setattr(stt_mod, "_module_available", lambda name: name != "funasr")

        with caplog.at_level(logging.WARNING, logger="jarvis.services.stt"):
            stt_mod.get_stt_engine("paraformer", ollama_client=MagicMock())

        assert [r for r in caplog.records if "回退" in r.getMessage()]


class TestParaformerPipeline:
    def test_autoloads_vad_and_punc_submodels(self, monkeypatch):
        """主模型目录只有 ASR 主干; 漏传 vad/punc 会导致无标点 + 汉字间空格。"""
        import asyncio
        import sys
        import types

        from jarvis.services.stt.paraformer import ParaformerSTT

        captured = {}
        fake_funasr = types.ModuleType("funasr")

        def fake_automodel(**kwargs):
            captured.update(kwargs)
            return object()

        fake_funasr.AutoModel = fake_automodel
        monkeypatch.setitem(sys.modules, "funasr", fake_funasr)

        engine = ParaformerSTT(device="cpu")
        asyncio.run(engine._load())

        assert captured["vad_model"] == ParaformerSTT.VAD_MODEL
        assert captured["punc_model"] == ParaformerSTT.PUNC_MODEL
        assert captured["device"] == "cpu"

    def test_warmup_loads_model(self, monkeypatch):
        """startup 预热应真正加载模型, 让首次请求走热路径 (~0.3s)。"""
        import asyncio
        import sys
        import types

        from jarvis.services.stt.paraformer import ParaformerSTT

        fake_funasr = types.ModuleType("funasr")
        fake_funasr.AutoModel = lambda **kwargs: object()
        monkeypatch.setitem(sys.modules, "funasr", fake_funasr)

        engine = ParaformerSTT(device="cpu")
        assert not engine.is_ready()

        asyncio.run(engine.warmup())

        assert engine.is_ready()


class TestRealEnvironment:
    """直接复现用户报错的场景 (本机 funasr 缺失)。"""

    def test_paraformer_request_does_not_explode_without_funasr(self):
        if stt_mod._module_available("funasr"):
            pytest.skip("本机已安装 funasr, 该场景不适用")

        engine = stt_mod.get_stt_engine("paraformer", ollama_client=MagicMock())

        assert engine.backend_name() == "whisper"
