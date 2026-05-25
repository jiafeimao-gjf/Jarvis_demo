# jarvis/core/voice_engine.py
"""语音引擎 - Pipeline Pattern 实现"""
import base64
from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional
from jarvis.utils.logger import get_logger

logger = get_logger(__name__)


class PipelineStage(ABC):
    """管道阶段抽象基类（Pipeline Pattern）"""

    @abstractmethod
    async def process(self, data: any) -> any:
        """处理数据"""
        pass


class VoiceActivityDetectionStage(PipelineStage):
    """语音活动检测阶段"""

    def __init__(self, threshold: float = 0.02):
        self.threshold = threshold

    async def process(self, audio_data: bytes) -> bytes:
        """检测是否包含语音"""
        # 简化实现：实际应使用 VAD 模型
        return audio_data  # 直接透传


class NoiseReductionStage(PipelineStage):
    """降噪阶段"""

    async def process(self, audio_data: bytes) -> bytes:
        """音频降噪"""
        # 简化实现：实际应使用降噪模型（如 RNNoise）
        return audio_data


class SpeechToTextStage(PipelineStage):
    """语音转文字阶段"""

    def __init__(self):
        self._last_transcript = ""

    async def process(self, audio_data: bytes) -> str:
        """STT - 实际由浏览器 Web Speech API 或后端 Whisper 处理"""
        # 这里返回空字符串，实际 STT 由前端或专用服务处理
        return ""


class VoicePipeline:
    """语音处理管道（Pipeline Pattern）"""

    def __init__(self):
        self.stages: list[PipelineStage] = []

    def add_stage(self, stage: PipelineStage):
        """添加处理阶段"""
        self.stages.append(stage)
        return self

    async def execute(self, audio_data: bytes) -> str:
        """执行管道"""
        data = audio_data
        for stage in self.stages:
            data = await stage.process(data)
            if isinstance(data, str) and data:
                # 如果中间阶段返回了文字（比如 STT），直接返回
                return data
        return str(data) if data else ""


class VoiceEngine:
    """语音引擎 - 协调语音输入输出"""

    def __init__(self):
        self.pipeline = VoicePipeline()
        self._setup_pipeline()
        self.tts_provider = "browser"  # browser | qwen3-tts
        logger.info("VoiceEngine initialized")

    def _setup_pipeline(self):
        """配置语音处理管道"""
        self.pipeline.add_stage(VoiceActivityDetectionStage()) \
                      .add_stage(NoiseReductionStage())

    async def process_voice_input(self, audio_data: bytes) -> str:
        """处理语音输入"""
        result = await self.pipeline.execute(audio_data)
        logger.debug(f"Voice input processed: {len(audio_data)} bytes -> '{result}'")
        return result

    async def text_to_speech(self, text: str) -> dict:
        """文字转语音 - 返回播放指令"""
        if self.tts_provider == "browser":
            # 前端处理 TTS
            return {"type": "browser_tts", "text": text}
        else:
            # 后端 Qwen3-TTS 处理
            return await self._qwen3_tts(text)

    async def _qwen3_tts(self, text: str) -> dict:
        """调用 Qwen3-TTS"""
        # TODO: 实现 Qwen3-TTS 调用
        logger.warning("Qwen3-TTS not yet implemented")
        return {"type": "browser_tts", "text": text}

    async def stream_audio(self, audio_data: bytes) -> AsyncIterator[bytes]:
        """流式处理音频"""
        # 分块处理音频流
        chunk_size = 4096
        for i in range(0, len(audio_data), chunk_size):
            chunk = audio_data[i:i + chunk_size]
            yield chunk

    def to_dict(self) -> dict:
        """导出状态"""
        return {
            "tts_provider": self.tts_provider,
            "pipeline_stages": len(self.pipeline.stages)
        }