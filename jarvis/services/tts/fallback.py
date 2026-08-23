# jarvis/services/tts/fallback.py
"""TTS 降级协议 — 后端统一返回 dict，前端按 type 路由。

降级链:
  1. F5-TTS 可用 + ref 完整  →  {"type": "voice_clone", "audio_url": ..., "duration": ...}
  2. F5-TTS 不可用 / 异常    →  {"type": "browser_tts", "text": ...}  (前端 SpeechSynthesis)
"""


def browser_tts_payload(text: str) -> dict:
    """降级到浏览器 TTS。前端 speechSynthesis.speak(text)。"""
    return {"type": "browser_tts", "text": text}


def voice_clone_url_payload(
    audio_url: str,
    duration: float,
    text: str,
    mime: str = "audio/wav",
) -> dict:
    """后端 F5-TTS 同步合成 wav 后的返回。前端 <audio src=audio_url>。"""
    return {
        "type": "voice_clone",
        "audio_url": audio_url,
        "duration": duration,
        "text": text,
        "mime": mime,
    }