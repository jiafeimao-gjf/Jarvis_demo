# jarvis/services/ai/base.py
"""AI Client Base Interface"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, AsyncIterator


@dataclass
class TokenUsage:
    """Token usage statistics"""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class ResponseMetrics:
    """Response performance metrics"""
    latency_ms: float = 0.0
    provider_latency_ms: Optional[float] = None


@dataclass
class AIResponse:
    """AI response with metadata"""
    content: str
    model: str
    provider: str
    done: bool = True
    usage: Optional[TokenUsage] = None
    metrics: Optional[ResponseMetrics] = None
    raw: Optional[dict] = None
    content_blocks: Optional[list] = None  # For tool_use blocks in Anthropic


class AIClient(ABC):
    """Abstract base class for AI providers (Strategy Pattern)"""

    def __init__(self, model: str, provider: str):
        self.model = model
        self.provider = provider

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        stream: bool = True,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        system: Optional[str] = None,
    ) -> AIResponse:
        """Generate text from a single prompt"""
        pass

    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
        stream: bool = True,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> AIResponse:
        """Multi-message chat completion"""
        pass

    @abstractmethod
    async def chat_stream(
        self,
        messages: list[dict],
    ) -> AsyncIterator[str]:
        """Stream chat completion tokens"""
        pass

    @abstractmethod
    async def vision_analyze(
        self,
        image_data: bytes,
        prompt: str,
    ) -> str:
        """Analyze image and return description"""
        pass

    @abstractmethod
    async def transcribe_audio(
        self,
        audio_data: bytes,
        **kwargs,
    ) -> str:
        """Transcribe audio data to text (STT)"""
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if provider is available"""
        pass

    async def list_models(self) -> list[dict]:
        """List available models (default implementation)"""
        return []

    async def close(self):
        """Clean up resources"""
        pass