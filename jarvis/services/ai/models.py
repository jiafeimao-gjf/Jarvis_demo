# jarvis/services/ai/models.py
"""AI Models and Provider Definitions"""
from enum import Enum
from dataclasses import dataclass
from typing import Optional


class Provider(Enum):
    """Supported AI providers"""
    OLLAMA = "ollama"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    MINIMAX = "minimax"


@dataclass(frozen=True)
class ModelInfo:
    """Model metadata"""
    provider: Provider
    model_id: str  # Provider-specific ID
    display_name: str
    supports_vision: bool = False
    supports_audio: bool = False
    supports_streaming: bool = True
    context_window: Optional[int] = None
    per_1k_cost: Optional[float] = None


# Model registry - add models here
MODELS: dict[str, ModelInfo] = {
    # Ollama (local)
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
    "qwen3.5:9b-q8_0": ModelInfo(
        provider=Provider.OLLAMA,
        model_id="qwen3.5:9b-q8_0",
        display_name="Qwen3.5 9B Q8",
        supports_vision=True,
    ),
    "llama3:8b": ModelInfo(
        provider=Provider.OLLAMA,
        model_id="llama3:8b",
        display_name="Llama3 8B",
    ),
    # Ollama Whisper (STT)
    "sendmeaiohyeah/whisper-large-v2": ModelInfo(
        provider=Provider.OLLAMA,
        model_id="sendmeaiohyeah/whisper-large-v2",
        display_name="Whisper Large v2",
        supports_audio=True,
    ),
    # OpenAI
    "gpt-4o-mini": ModelInfo(
        provider=Provider.OPENAI,
        model_id="gpt-4o-mini",
        display_name="GPT-4o Mini",
        context_window=128000,
        per_1k_cost=0.00015,
    ),
    "gpt-4o": ModelInfo(
        provider=Provider.OPENAI,
        model_id="gpt-4o",
        display_name="GPT-4o",
        supports_vision=True,
        context_window=128000,
        per_1k_cost=0.0025,
    ),
    "gpt-4o-mini-vision": ModelInfo(
        provider=Provider.OPENAI,
        model_id="gpt-4o-mini",
        display_name="GPT-4o Mini Vision",
        supports_vision=True,
        context_window=128000,
        per_1k_cost=0.00015,
    ),
    # Anthropic
    "claude-3-haiku": ModelInfo(
        provider=Provider.ANTHROPIC,
        model_id="claude-3-haiku-20240307",
        display_name="Claude 3 Haiku",
        supports_vision=True,
        context_window=200000,
        per_1k_cost=0.0008,
    ),
    "claude-3-sonnet": ModelInfo(
        provider=Provider.ANTHROPIC,
        model_id="claude-3-sonnet-20240229",
        display_name="Claude 3 Sonnet",
        supports_vision=True,
        context_window=200000,
        per_1k_cost=0.003,
    ),
    "claude-3-5-sonnet": ModelInfo(
        provider=Provider.ANTHROPIC,
        model_id="claude-3-5-sonnet-20241022",
        display_name="Claude 3.5 Sonnet",
        supports_vision=True,
        context_window=200000,
        per_1k_cost=0.003,
    ),
    # MiniMax
    "MiniMax-M2.7": ModelInfo(
        provider=Provider.MINIMAX,
        model_id="MiniMax-M2.7",
        display_name="MiniMax M2.7",
        supports_vision=False,
        context_window=1000000,
        per_1k_cost=0.0,
    ),
}


def get_model(model_id: str) -> Optional[ModelInfo]:
    """Get model info by ID"""
    return MODELS.get(model_id)


def list_models(provider: Optional[Provider] = None) -> list[str]:
    """List available models, optionally filtered by provider"""
    if provider:
        return [mid for mid, mi in MODELS.items() if mi.provider == provider]
    return list(MODELS.keys())


def find_vision_model(provider: Provider) -> Optional[str]:
    """Find first vision-capable model for a provider"""
    for mid, mi in MODELS.items():
        if mi.provider == provider and mi.supports_vision:
            return mid
    return None


def find_audio_model(provider: Provider) -> Optional[str]:
    """Find first audio-capable (STT) model for a provider"""
    for mid, mi in MODELS.items():
        if mi.provider == provider and mi.supports_audio:
            return mid
    return None