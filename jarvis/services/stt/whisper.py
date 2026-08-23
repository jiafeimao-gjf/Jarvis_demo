# jarvis/services/stt/whisper.py
"""Whisper STT — openai-whisper base (fallback backend)

保留作为 paraformer 不可用时的回退路径。Whisper 实际推理逻辑在
OllamaAdapter.transcribe_audio() (复用其 ffmpeg 解码 + lazy model 加载)。
"""
from typing import Any

from jarvis.services.stt.base import STTEngine
from jarvis.utils.logger import get_logger

logger = get_logger(__name__)


class WhisperSTT(STTEngine):
    """openai-whisper base (lazy load via OllamaAdapter)."""

    def __init__(self, ollama_adapter: Any):
        self._client = ollama_adapter
        logger.info("[Whisper] initialized (delegates to OllamaAdapter.transcribe_audio)")

    def backend_name(self) -> str:
        return "whisper"

    async def transcribe(self, audio_data: bytes) -> str:
        if not audio_data:
            logger.warning("[Whisper] empty audio data")
            return ""
        # OllamaAdapter 内部: ffmpeg 解码 WebM → WAV → whisper.transcribe()
        return await self._client.transcribe_audio(audio_data)