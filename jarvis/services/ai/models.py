# jarvis/services/ai/models.py
"""Ollama Models and Provider Definitions"""
from enum import Enum
from dataclasses import dataclass
from typing import Optional


class Provider(Enum):
    """AI provider — Ollama only (all local)"""
    OLLAMA = "ollama"


@dataclass(frozen=True)
class ModelInfo:
    """Model metadata"""
    provider: Provider
    model_id: str
    display_name: str
    supports_vision: bool = False
    supports_audio: bool = False
    supports_streaming: bool = True
    context_window: Optional[int] = None


# Model registry
MODELS: dict[str, ModelInfo] = {
    # Chat
    "qwen3:4b": ModelInfo(
        provider=Provider.OLLAMA,
        model_id="qwen3:4b",
        display_name="Qwen3 4B",
    ),
    "qwen3:8b": ModelInfo(
        provider=Provider.OLLAMA,
        model_id="qwen3:8b",
        display_name="Qwen3 8B",
    ),
    "qwen3.5:9b": ModelInfo(
        provider=Provider.OLLAMA,
        model_id="qwen3.5:9b",
        display_name="Qwen3.5 9B",
        supports_vision=True,
    ),
    "llama3:8b": ModelInfo(
        provider=Provider.OLLAMA,
        model_id="llama3:8b",
        display_name="Llama3 8B",
    ),
    # STT — handled by local openai-whisper, listed for reference
    "sendmeaiohyeah/whisper-large-v2": ModelInfo(
        provider=Provider.OLLAMA,
        model_id="sendmeaiohyeah/whisper-large-v2",
        display_name="Whisper Large v2",
        supports_audio=True,
    ),
}


def get_model(model_id: str) -> Optional[ModelInfo]:
    return MODELS.get(model_id)


def list_models(provider: Optional[Provider] = None) -> list[str]:
    if provider:
        return [mid for mid, mi in MODELS.items() if mi.provider == provider]
    return list(MODELS.keys())


def find_vision_model(provider: Provider) -> Optional[str]:
    for mid, mi in MODELS.items():
        if mi.provider == provider and mi.supports_vision:
            return mid
    return None


def find_audio_model(provider: Provider) -> Optional[str]:
    for mid, mi in MODELS.items():
        if mi.provider == provider and mi.supports_audio:
            return mid
    return None
