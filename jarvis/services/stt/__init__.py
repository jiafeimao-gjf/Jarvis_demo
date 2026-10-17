# jarvis/services/stt/__init__.py
"""STT 引擎工厂 — 统一接口，按配置选择后端。

使用:
    from jarvis.services.stt import get_stt_engine
    engine = get_stt_engine("paraformer", ollama_client=ollama)
    text = await engine.transcribe(audio_bytes)

回退行为:
    请求的 backend 依赖缺失时（如 funasr 未安装），自动回退到下一个可用后端，
    而不是等到模型加载阶段才抛 ModuleNotFoundError。参见 resolve_backend()。
"""
import importlib.util
from typing import Any, Optional

from jarvis.services.stt.base import STTEngine
from jarvis.utils.logger import get_logger

logger = get_logger(__name__)

_engine: Optional[STTEngine] = None

# backend → 它依赖的可导入模块名
_BACKEND_DEPS = {
    "paraformer": "funasr",
    "whisper": "whisper",
}

# backend 不可用时的回退目标
_FALLBACK = {
    "paraformer": "whisper",
}

_INSTALL_HINT = (
    "安装依赖后重试: `pip install funasr` (推荐, 中文优化的 paraformer) "
    "或 `pip install openai-whisper` (whisper)"
)


def _module_available(name: str) -> bool:
    """模块是否可被 import。

    用 find_spec 探测而非真正 import — paraformer 的 funasr 会连带拉起
    torch/modelscope, 只为了探测可用性而导入代价太高。
    """
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def resolve_backend(backend: str, *, warn: bool = True) -> str:
    """把请求的 backend 解析成实际可用的 backend。

    当前只有 paraformer → whisper 这一条回退链。回退只发生在依赖缺失时；
    未知 backend 原样返回，交给 get_stt_engine 报错。

    warn=False 用于状态查询 (/api/status 每分钟轮询) — 否则同一条回退
    warning 会刷屏。
    """
    dep = _BACKEND_DEPS.get(backend)
    if dep and not _module_available(dep):
        fallback = _FALLBACK.get(backend)
        if warn:
            logger.warning(
                f"[STT] backend={backend!r} 依赖 {dep!r} 未安装"
                + (f" → 回退 {fallback!r}" if fallback else "")
            )
        if fallback:
            return resolve_backend(fallback, warn=warn)
    return backend


def get_stt_engine(
    backend: str = "paraformer",
    ollama_client: Optional[Any] = None,
) -> STTEngine:
    """获取（或创建）STT 引擎单例。

    Args:
        backend: "paraformer" (推荐，中文优化) | "whisper" (fallback)
                 依赖缺失时自动回退（见 resolve_backend）
        ollama_client: whisper 后端所需的 OllamaAdapter 实例（仅 whisper 时使用）
    """
    global _engine

    if backend not in _BACKEND_DEPS:
        raise ValueError(f"Unknown STT backend: {backend!r} (use 'paraformer' or 'whisper')")

    # 先解析回退，再按解析结果做缓存键 — 否则每次都重建引擎
    resolved = resolve_backend(backend)

    if _engine is not None and _engine.backend_name() == resolved:
        return _engine

    dep = _BACKEND_DEPS[resolved]
    if not _module_available(dep):
        raise RuntimeError(
            f"STT 引擎不可用: 请求 backend={backend!r}, 回退 backend={resolved!r} "
            f"缺少依赖 {dep!r}. {_INSTALL_HINT}"
        )

    if resolved == "paraformer":
        from jarvis.services.stt.paraformer import ParaformerSTT
        _engine = ParaformerSTT()
    else:  # whisper
        if ollama_client is None:
            raise ValueError("whisper backend requires `ollama_client`")
        from jarvis.services.stt.whisper import WhisperSTT
        _engine = WhisperSTT(ollama_client)

    suffix = "" if backend == resolved else f" (requested: {backend})"
    logger.info(f"[STT] active backend: {_engine.backend_name()}{suffix}")
    return _engine


def reset_stt_engine() -> None:
    """重置单例（测试 / 切换配置时使用）"""
    global _engine
    _engine = None


def get_stt_status() -> dict:
    """STT 子系统状态 — 供 /api 状态端点暴露, 避免配置问题只出现在日志里。"""
    from jarvis.config import settings

    requested = settings.stt_backend
    return {
        "requested_backend": requested,
        "effective_backend": resolve_backend(requested, warn=False),
        "paraformer_available": _module_available("funasr"),
        "whisper_available": _module_available("whisper"),
        "loaded_backend": _engine.backend_name() if _engine else None,
    }


__all__ = [
    "STTEngine",
    "get_stt_engine",
    "get_stt_status",
    "resolve_backend",
    "reset_stt_engine",
]
