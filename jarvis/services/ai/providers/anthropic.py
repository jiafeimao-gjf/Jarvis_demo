# jarvis/services/ai/providers/anthropic.py
"""Anthropic (Claude) Provider Adapter"""
import os
import base64
import httpx
from typing import Optional, AsyncIterator
from jarvis.services.ai.base import AIClient, AIResponse, TokenUsage
from jarvis.services.ai.exceptions import ProviderNotAvailableError, AuthenticationError, RateLimitError
from jarvis.utils.logger import get_logger

logger = get_logger(__name__)


class AnthropicAdapter(AIClient):
    """Anthropic Claude API adapter"""

    BASE_URL = "https://api.anthropic.com/v1"
    API_VERSION = "2023-06-01"

    def __init__(
        self,
        model: str,
        api_key: Optional[str] = None,
        base_url: str = "https://api.anthropic.com/v1",
        timeout: float = 60.0,
    ):
        super().__init__(model=model, provider="anthropic")
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self.base_url = base_url.rstrip("/")
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
            anthropic_messages.append({
                "role": msg["role"],
                "content": msg["content"]
            })

        payload = {
            "model": self.model,
            "messages": anthropic_messages,
            "stream": stream,
            "temperature": temperature,
            "max_tokens": max_tokens or 4096,  # Required by Anthropic
        }

        try:
            response = await self.client.post("/messages", json=payload)
            response.raise_for_status()
            data = response.json()

            content = data["content"][0]["text"]

            return AIResponse(
                content=content,
                model=self.model,
                provider="anthropic",
                done=True,
                usage=TokenUsage(
                    prompt_tokens=data.get("usage", {}).get("input_tokens", 0),
                    completion_tokens=data.get("usage", {}).get("output_tokens", 0),
                    total_tokens=data.get("usage", {}).get("input_tokens", 0) + data.get("usage", {}).get("output_tokens", 0),
                ),
                raw=data
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise AuthenticationError("anthropic", "Invalid API key")
            elif e.response.status_code == 429:
                raise RateLimitError("anthropic", "Rate limit exceeded")
            raise ProviderNotAvailableError("anthropic", str(e))
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