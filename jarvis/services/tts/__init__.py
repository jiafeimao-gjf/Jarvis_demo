# jarvis/services/tts/__init__.py
"""TTS 子包 — 声音克隆模块（基于 F5-TTS）"""
from jarvis.services.tts.f5_tts_service import F5TTSBridge, F5TTSUnavailable, f5_tts
from jarvis.services.tts.voice_ref_manager import VoiceRefManager, voice_ref_manager
from jarvis.services.tts.sentence_splitter import split_by_punctuation, _find_split
from jarvis.services.tts.pcm_chunker import encode_pcm_chunk
from jarvis.services.tts.fallback import browser_tts_payload, voice_clone_url_payload

__all__ = [
    "F5TTSBridge",
    "F5TTSUnavailable",
    "f5_tts",
    "VoiceRefManager",
    "voice_ref_manager",
    "split_by_punctuation",
    "_find_split",
    "encode_pcm_chunk",
    "browser_tts_payload",
    "voice_clone_url_payload",
]