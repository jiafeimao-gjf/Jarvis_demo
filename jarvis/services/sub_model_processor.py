# jarvis/services/sub_model_processor.py
"""子模型处理器 — 多模态输入转文本, 再合并到主对话引擎"""
import base64
from enum import Enum
from pathlib import Path
from typing import Optional

from jarvis.services.ai.models import Provider, find_audio_model
from jarvis.config import settings
from jarvis.utils.logger import get_logger

logger = get_logger(__name__)


class SubModelType(str, Enum):
    """子模型类型"""
    AUDIO = "audio"
    VISION = "vision"


class SubModelProcessor:
    """子模型处理器: STT / Vision → 文本 → 注入主对话

    职责:
      - 查找合适的子模型 (sendmeaiohyeah/whisper-large-v2 for STT, qwen3.5:9b-q8_0 for vision)
      - 调用子模型进行原始输入→文本转换
      - 返回纯文本, 由调用方注入 chat_engine
    """

    def __init__(self, ai_router=None):
        """ai_router 为 AIRouter 实例, 由 mediator 传入"""
        self._router = ai_router
        self._stt_model: Optional[str] = None
        self._vision_model: Optional[str] = None
        logger.info("SubModelProcessor initialized")

    def set_router(self, ai_router):
        """设置 AI Router (延迟绑定)"""
        self._router = ai_router

    @property
    def stt_model(self) -> str:
        """STT 模型名 — 优先注册表, 回退配置"""
        if self._stt_model is None:
            found = find_audio_model(Provider.OLLAMA)
            self._stt_model = found or settings.ai.ollama.stt_model
        return self._stt_model

    @property
    def vision_model(self) -> str:
        """Vision 模型名"""
        if self._vision_model is None:
            from jarvis.services.ai.models import find_vision_model
            found = find_vision_model(Provider.OLLAMA)
            self._vision_model = found or settings.ai.ollama.vision_model
        return self._vision_model

    async def process_audio(self, audio_data: bytes) -> str:
        """STT: 音频 bytes → 文本"""
        if not self._router:
            logger.error("SubModelProcessor: no AI Router set")
            return ""

        try:
            client = self._router._get_client("ollama", self.stt_model)
            text = await client.transcribe_audio(audio_data)
            result = text.strip() if text else ""
            logger.info(f"STT result ({len(result)} chars): {result[:100]}...")
            return result
        except Exception as e:
            logger.error(f"Audio transcription failed: {e}")
            return ""

    async def process_image(
        self,
        image_data: bytes,
        prompt: str = "请描述这张图片中的内容",
    ) -> str:
        """Vision: 图片 bytes → 文本描述"""
        if not self._router:
            logger.error("SubModelProcessor: no AI Router set")
            return ""

        try:
            # Base64-encode the image for Ollama vision API
            image_base64 = base64.b64encode(image_data).decode()

            result = await self._router.vision_analyze(
                image_data,
                prompt,
                model=self.vision_model,
                provider="ollama",
            )
            logger.info(f"Vision result ({len(result)} chars): {result[:100]}...")
            return result
        except Exception as e:
            logger.error(f"Image analysis failed: {e}")
            return ""

    def get_status(self) -> dict:
        """导出状态"""
        return {
            "stt_model": self.stt_model,
            "vision_model": self.vision_model,
            "router_ready": self._router is not None,
        }
