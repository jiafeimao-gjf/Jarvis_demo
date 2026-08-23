# jarvis/services/tts/pcm_chunker.py
"""PCM int16 bytes → SSE event payload（base64 + 元信息）。"""
import base64
import json


def encode_pcm_chunk(
    index: int,
    pcm: bytes,
    sample_rate: int = 24000,
    channels: int = 1,
    sample_width: int = 2,
    duration_ms: int = 0,
) -> str:
    """返回 SSE `data:` 行内容（不含 `event:` 行）。

    F5-TTS 默认输出: 24kHz mono int16 LE。
    前端 usePCMPlayer 按 sample_rate 创建 AudioContext 播放。
    """
    return json.dumps(
        {
            "type": "audio_chunk",
            "index": index,
            "sample_rate": sample_rate,
            "channels": channels,
            "sample_width": sample_width,
            "duration_ms": duration_ms,
            "pcm_b64": base64.b64encode(pcm).decode("ascii"),
        },
        ensure_ascii=False,
    )