# jarvis/services/stt/__init__.py
"""STT 引擎工厂 — 统一接口，按配置选择后端。

使用:
    from jarvis.services.stt import get_stt_engine
    engine = get_stt_engine("paraformer", ollama_client=ollama)
    text = await engine.transcribe(audio_bytes)
"""
from typing import Any, Optional

from jarvis.services.stt.base import STTEngine
from jarvis.utils.logger import get_logger

logger = get_logger(__name__)

_engine: Optional[STTEngine] = None


def get_stt_engine(
    backend: str = "paraformer",
    ollama_client: Optional[Any] = None,
) -> STTEngine:
    """获取（或创建）STT 引擎单例。

    Args:
        backend: "paraformer" (推荐，中文优化) | "whisper" (fallback)
        ollama_client: whisper 后端所需的 OllamaAdapter 实例（仅 backend="whisper" 时使用）
    """
    global _engine
    # 缓存命中：后端一致就直接返回
    if _engine is not None and _engine.backend_name() == backend:
        return _engine

    if backend == "paraformer":
        from jarvis.services.stt.paraformer import ParaformerSTT
        _engine = ParaformerSTT()
    elif backend == "whisper":
        from jarvis.services.stt.whisper import WhisperSTT
        if ollama_client is None:
            raise ValueError("whisper backend requires `ollama_client`")
        _engine = WhisperSTT(ollama_client)
    else:
        raise ValueError(f"Unknown STT backend: {backend!r} (use 'paraformer' or 'whisper')")

    logger.info(f"[STT] active backend: {_engine.backend_name()}")
    return _engine


def reset_stt_engine() -> None:
    """重置单例（测试 / 切换配置时使用）"""
    global _engine
    _engine = None


__all__ = ["STTEngine", "get_stt_engine", "reset_stt_engine"]