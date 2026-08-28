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
    thinking: Optional[str] = None  # Model reasoning/thinking content
    # PR3: 标识 provider 使用的 tool-call 协议, AgentLoopRunner 据此分发 tool_result 格式
    # "anthropic" — Anthropic /v1/messages 协议 (Ollama 默认走这个, 兼容模式)
    # "openai"    — OpenAI /v1/chat/completions 协议 (OpenAI / MiniMax)
    provider_protocol: Optional[str] = None


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
        *,
        call_id: Optional[str] = None,
    ) -> AIResponse:
        """Multi-message chat completion.

        call_id:  LLMCallLogger 提供的 call record id. adapter 在 HTTP 调用前后
                   调用 enrich_raw_body(call_id, raw_request=..., raw_response=...)
                   把原始 HTTP body 写回日志. None 时 adapter 不写日志.
        """
        pass

    @abstractmethod
    async def chat_stream(
        self,
        messages: list[dict],
        *,
        call_id: Optional[str] = None,
    ) -> AsyncIterator[str]:
        """Stream chat completion tokens.

        call_id: 同 chat() — adapter 拿它写 raw_stream_events 到日志.
        """
        # Note: 子类应实现此方法. 实际 chat_stream_full() 是被 router 调用的主入口.
        yield ""  # pragma: no cover

    async def chat_stream_full(
        self,
        messages: list[dict],
        *,
        call_id: Optional[str] = None,
    ) -> AsyncIterator[dict]:
        """Stream chat with structured events (text, thinking, tool_use).

        Yields dict events:
          {"type": "text_start"} / {"type": "text", "content": "..."}
          {"type": "thinking_start"} / {"type": "thinking", "content": "..."} / {"type": "thinking_end"}
          {"type": "tool_use_start", "name": "...", "id": "..."}
          {"type": "tool_use_delta", "partial_json": "..."}
          {"type": "tool_use_end", "name": "...", "id": "...", "input": {...}}
          {"type": "message_delta", "stop_reason": "..."}
          {"type": "message_stop"}
          {"type": "error", "content": "..."}

        call_id: 透传给底层 adapter 的 chat_stream — 让 adapter 把 raw_stream_events
                 写回日志.
        """
        # Default: fall back to non-streaming chat, yield as single text block
        resp = await self.chat(messages, stream=False, call_id=call_id)
        if resp.thinking:
            yield {"type": "thinking_start"}
            yield {"type": "thinking", "content": resp.thinking}
            yield {"type": "thinking_end"}
        if resp.content:
            yield {"type": "text_start"}
            yield {"type": "text", "content": resp.content}
        yield {"type": "message_stop"}

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