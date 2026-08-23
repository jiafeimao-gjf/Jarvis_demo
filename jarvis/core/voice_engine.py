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
        # tts_provider: browser (默认) | f5_tts (声音克隆, 启用 voice_clone 即可)
        self.tts_provider = "browser"
        logger.info("VoiceEngine initialized")

    def _setup_pipeline(self):
        """配置语音处理管道"""
        self.pipeline.add_stage(VoiceActivityDetectionStage()) \
                      .add_stage(NoiseReductionStage())

    async def process_voice_input(self, audio_data: bytes) -> str:
        """处理语音输入（已迁移到 SubModelProcessor.process_audio，本方法保留兼容）"""
        result = await self.pipeline.execute(audio_data)
        logger.debug(f"Voice input processed: {len(audio_data)} bytes -> '{result}'")
        return result

    async def text_to_speech(self, text: str) -> dict:
        """文字转语音 → 返回 dict，前端按 type 路由。

        返回形态:
          - {type: "voice_clone", audio_url, duration, text, mime}  F5-TTS 成功
          - {type: "browser_tts", text}                              降级

        F5-TTS 不可用 / 缺 ref / 推理异常 → 自动降级到浏览器 TTS。
        """
        from jarvis.services.tts import (
            F5TTSUnavailable,
            browser_tts_payload,
            f5_tts,
            voice_clone_url_payload,
        )

        if not text or not text.strip():
            return browser_tts_payload(text or "")

        if not f5_tts.available:
            return browser_tts_payload(text)

        try:
            import time
            output_name = f"clone_{int(time.time() * 1000)}.wav"
            result = f5_tts.synthesize_to_wav(text, output_name=output_name)
            logger.info(
                f"[TTS] cloned {len(text)} chars → {result['output_url']}, "
                f"duration={result['duration']:.2f}s"
            )
            return voice_clone_url_payload(
                audio_url=result["output_url"],
                duration=result["duration"],
                text=text,
            )
        except F5TTSUnavailable as e:
            logger.warning(f"[TTS] 克隆不可用，降级: {e}")
            return browser_tts_payload(text)
        except Exception as e:
            logger.error(f"[TTS] 克隆失败，降级: {e}", exc_info=True)
            return browser_tts_payload(text)

    async def _qwen3_tts(self, text: str) -> dict:
        """旧接口保留（Qwen3-TTS 尚未实现）。"""
        logger.warning("Qwen3-TTS not yet implemented, fallback to browser")
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