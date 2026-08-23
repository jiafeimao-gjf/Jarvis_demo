# jarvis/services/stt/base.py
"""STT 引擎抽象基类"""
from abc import ABC, abstractmethod


class STTEngine(ABC):
    """语音转文字 (Speech-to-Text) 引擎抽象接口。

    所有 STT 后端（paraformer / whisper / 云端 API）都实现这个接口，
    由 SubModelProcessor 统一调用，与 chat provider 解耦。
    """

    @abstractmethod
    async def transcribe(self, audio_data: bytes) -> str:
        """音频二进制 (webm/wav/mp3...) → 文本。

        输入来自浏览器 MediaRecorder (audio/webm, Opus 编码)，
        实现方负责内部解码（如有需要）。
        """
        pass

    @abstractmethod
    def backend_name(self) -> str:
        """返回后端标识（用于日志与配置切换）"""
        pass

    def is_ready(self) -> bool:
        """模型是否已加载。默认 True（懒加载的后端首次 transcribe 才加载）"""
        return True