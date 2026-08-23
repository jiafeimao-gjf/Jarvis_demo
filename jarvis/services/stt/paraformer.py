# jarvis/services/stt/paraformer.py
"""Paraformer STT — 阿里达摩院 Paraformer-large 中文 ASR (funasr 实现)

对比 whisper-base:
  ✓ 中文场景显著优于 whisper（词错率 ~1/3）
  ✓ 内置 VAD（语音活动检测）+ 标点恢复
  ✓ 16kHz 采样率针对性训练
  ✓ Apple Silicon MPS 加速

模型: iic/speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-pytorch
"""
import asyncio
from typing import Optional

from jarvis.services.stt.base import STTEngine
from jarvis.utils.logger import get_logger

logger = get_logger(__name__)


class ParaformerSTT(STTEngine):
    """阿里达摩院 Paraformer-large 中文 ASR"""

    MODEL = "iic/speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-pytorch"
    REVISION = "v2.0.4"

    def __init__(self, device: Optional[str] = None, batch_size_s: int = 300):
        self._device = device  # None = 自动检测 (mps/cpu)
        self._batch_size_s = batch_size_s
        self._model = None
        self._loading_lock = asyncio.Lock()
        logger.info(f"[Paraformer] initialized (device={device or 'auto'})")

    def backend_name(self) -> str:
        return "paraformer"

    def is_ready(self) -> bool:
        return self._model is not None

    async def transcribe(self, audio_data: bytes) -> str:
        """音频 bytes → 文本

        funasr 的 AutoModel.generate() 接受:
          - 文件路径 (str / Path)
          - URL (str)
          - 音频二进制 (bytes) — 自动识别格式 (wav/mp3/m4a/...)
          - numpy ndarray
          - 嵌套列表 (batch)
        """
        if not audio_data:
            logger.warning("[Paraformer] empty audio data")
            return ""

        try:
            await self._ensure_loaded()
        except Exception as e:
            logger.error(f"[Paraformer] model load failed: {e}")
            raise

        # CPU/GPU 密集，放到线程池避免阻塞 event loop
        try:
            result = await asyncio.to_thread(
                self._model.generate,
                input=audio_data,
                batch_size_s=self._batch_size_s,
            )
        except Exception as e:
            logger.error(f"[Paraformer] generate failed: {type(e).__name__}: {e}")
            raise

        if not result:
            return ""
        text = result[0].get("text", "") if isinstance(result[0], dict) else ""
        return text.strip()

    async def _ensure_loaded(self):
        """懒加载模型（首次调用时加载，后续复用）"""
        if self._model is not None:
            return
        async with self._loading_lock:
            if self._model is not None:
                return
            await self._load()

    async def _load(self):
        """实际加载逻辑（在线程池中执行）"""
        import torch

        if self._device is None:
            if torch.backends.mps.is_available():
                self._device = "mps"
            elif torch.cuda.is_available():
                self._device = "cuda"
            else:
                self._device = "cpu"
        logger.info(f"[Paraformer] loading model on {self._device}...")

        from funasr import AutoModel

        def _create():
            return AutoModel(
                model=self.MODEL,
                model_revision=self.REVISION,
                device=self._device,
                batch_size_s=self._batch_size_s,
            )

        self._model = await asyncio.to_thread(_create)
        logger.info(f"[Paraformer] loaded on {self._device}")