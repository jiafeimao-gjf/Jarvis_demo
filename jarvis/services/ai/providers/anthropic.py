# jarvis/services/ai/providers/anthropic.py
"""Anthropic (Claude) Provider Adapter"""
import os
import base64
import httpx
from typing import Optional, AsyncIterator
from jarvis.services.ai.base import AIClient, AIResponse, TokenUsage
from jarvis.services.ai.exceptions import ProviderNotAvailableError, AuthenticationError, RateLimitError
from jarvis.services.ai.providers.anthropic_tools import build_anthropic_tools
from jarvis.utils.logger import get_logger

logger = get_logger(__name__)


MINIMAX_CONFIG = {
    "api_key": "sk-api-REDACTED-PLEASE-ROTATE-IN-MINIMAX-CONSOLE",
    "base_url": "https://api.minimaxi.com/anthropic/v1",
    "model": "MiniMax-M2.7",
}


class AnthropicAdapter(AIClient):
    """Anthropic Claude API adapter"""

    BASE_URL = "https://api.anthropic.com/v1"
    API_VERSION = "2023-06-01"

    def __init__(
        self,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 60.0,
        use_minimax: bool = False,
    ):
        if use_minimax:
            super().__init__(model=MINIMAX_CONFIG["model"], provider="minimax")
            self.api_key = MINIMAX_CONFIG["api_key"]
            self.base_url = "https://api.minimaxi.com/anthropic/v1"
        else:
            super().__init__(model=model or "claude-3-5-sonnet-20241022", provider="anthropic")
            self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
            self.base_url = (base_url or "https://api.anthropic.com/v1").rstrip("/")
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def client(self) -> httpx.AsyncClient:
        """Lazy-loaded HTTP client with auth"""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.timeout),
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": self.API_VERSION,
                    "Content-Type": "application/json"
                }
            )
        return self._client

    async def close(self):
        """Close HTTP client"""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def generate(
        self,
        prompt: str,
        stream: bool = True,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        system: Optional[str] = None,
    ) -> AIResponse:
        """Generate text (uses messages API internally)"""
        messages = []
        if system:
            messages.append({"role": "user", "content": system + "\n\n" + prompt})
        else:
            messages.append({"role": "user", "content": prompt})

        return await self._messages_request(messages, stream, temperature, max_tokens)

    async def chat(
        self,
        messages: list[dict],
        stream: bool = True,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> AIResponse:
        """Chat completion using messages API"""
        return await self._messages_request(messages, stream, temperature, max_tokens)

    async def _messages_request(
        self,
        messages: list[dict],
        stream: bool,
        temperature: float,
        max_tokens: int,
    ) -> AIResponse:
        """Make messages API request (Claude API format)"""
        # Convert messages format for Anthropic
        anthropic_messages = []
        for msg in messages:
            if msg.get("role") == "system":
                # Anthropic handles system differently
                continue

            # Handle content - can be string, list (tool_result blocks), or dict
            msg_content = msg.get("content", "")
            if isinstance(msg_content, list):
                # Keep as-is for tool_result blocks
                pass
            elif isinstance(msg_content, dict):
                # Single block - wrap in list
                msg_content = [msg_content]
            # else: string stays as-is

            anthropic_messages.append({
                "role": msg["role"],
                "content": msg_content
            })

        payload = {
            "model": self.model,
            "messages": anthropic_messages,
            "stream": False,  # Always use False for non-streaming JSON response
            "temperature": temperature,
            "max_tokens": max_tokens or 4096,  # Required by Anthropic
        }

        # 添加 tools（如果消息中没有 tool_result blocks）
        tools = build_anthropic_tools()
        if tools:
            payload["tools"] = tools

        try:
            response = await self.client.post("/messages", json=payload)
            response.raise_for_status()
            data = response.json()

            # Handle content array - find text content
            content = ""
            for item in data.get("content", []):
                if item.get("type") == "text":
                    content = item.get("text", "")
                    break

            return AIResponse(
                content=content,
                model=self.model,
                provider=self.provider,
                done=True,
                usage=TokenUsage(
                    prompt_tokens=data.get("usage", {}).get("input_tokens", 0),
                    completion_tokens=data.get("usage", {}).get("output_tokens", 0),
                    total_tokens=data.get("usage", {}).get("input_tokens", 0) + data.get("usage", {}).get("output_tokens", 0),
                ),
                raw=data,
                content_blocks=data.get("content", [])  # 保留完整的 content blocks
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise AuthenticationError("anthropic", "Invalid API key")
            elif e.response.status_code == 429:
                raise RateLimitError("anthropic", "Rate limit exceeded")
            raise ProviderNotAvailableError("anthropic", str(e))
        except KeyError as e:
            logger.error(f"Anthropic response parsing error: {e}, response: {data if 'data' in dir() else 'N/A'}")
            raise ProviderNotAvailableError("anthropic", f"Response parsing error: {e}")
        except httpx.HTTPError as e:
            logger.error(f"Anthropic messages error: {e}")
            raise ProviderNotAvailableError("anthropic", str(e))

    async def chat_stream(
        self,
        messages: list[dict],
    ) -> AsyncIterator[str]:
        """Stream chat completion tokens"""
        anthropic_messages = []
        for msg in messages:
            if msg.get("role") == "system":
                continue
            anthropic_messages.append({
                "role": msg["role"],
                "content": msg["content"]
            })

        payload = {
            "model": self.model,
            "messages": anthropic_messages,
            "stream": True,
            "max_tokens": 4096,
        }

        # 添加 tools
        tools = build_anthropic_tools()
        if tools:
            payload["tools"] = tools

        try:
            async with self.client.stream("POST", "/messages", json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        if line.strip() == "data: [DONE]":
                            break
                        try:
                            import json
                            data = json.loads(line[6:])
                            if data.get("type") == "content_block_delta":
                                content = data.get("delta", {}).get("text", "")
                                if content:
                                    yield content
                        except (json.JSONDecodeError, KeyError):
                            continue
        except httpx.HTTPError as e:
            logger.error(f"Anthropic chat stream error: {e}")
            yield f"Error: {str(e)}"

    async def vision_analyze(
        self,
        image_data: bytes,
        prompt: str,
    ) -> str:
        """Analyze image using vision model"""
        image_base64 = base64.b64encode(image_data).decode()

        payload = {
            "model": self.model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": image_base64
                        }
                    }
                ]
            }],
            "max_tokens": 1024
        }

        try:
            response = await self.client.post("/messages", json=payload)
            response.raise_for_status()
            data = response.json()

            return data["content"][0]["text"]
        except httpx.HTTPError as e:
            logger.error(f"Anthropic vision error: {e}")
            raise ProviderNotAvailableError("anthropic", str(e))

    async def health_check(self) -> bool:
        """Check if Anthropic API is accessible"""
        try:
            response = await self.client.post(
                "/messages",
                json={"max_tokens": 1, "messages": [{"role": "user", "content": "hi"}]}
            )
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Anthropic health check failed: {e}")
            return False