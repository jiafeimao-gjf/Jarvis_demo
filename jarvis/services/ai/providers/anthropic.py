# jarvis/services/ai/providers/anthropic.py
"""Anthropic (Claude) Provider Adapter"""
import os
import httpx
from typing import Optional, AsyncIterator
from jarvis.services.ai.base import AIClient, AIResponse, TokenUsage
from jarvis.services.ai.exceptions import ProviderNotAvailableError, AuthenticationError
from jarvis.utils.logger import get_logger

logger = get_logger(__name__)

API_VERSION = "2023-06-01"


class AnthropicAdapter(AIClient):
    """Anthropic Claude API adapter — implements /v1/messages"""

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
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.timeout),
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": API_VERSION,
                    "Content-Type": "application/json",
                },
            )
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    async def generate(self, prompt, stream=True, temperature=0.7,
                       max_tokens=2048, system=None) -> AIResponse:
        messages = [{"role": "user", "content": prompt}]
        return await self._messages(messages, temperature, max_tokens)

    async def chat(self, messages, stream=True, temperature=0.7,
                   max_tokens=2048) -> AIResponse:
        return await self._messages(messages, temperature, max_tokens)

    async def _messages(self, messages, temperature, max_tokens) -> AIResponse:
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens or 4096,
            "temperature": temperature,
        }
        try:
            resp = await self.client.post("/v1/messages", json=payload)
            if resp.status_code == 401:
                raise AuthenticationError("anthropic", "Invalid API key")
            resp.raise_for_status()
            data = resp.json()
            content = ""
            for block in data.get("content", []):
                if block.get("type") == "text":
                    content = block.get("text", "")
                    break
            return AIResponse(
                content=content,
                model=self.model,
                provider="anthropic",
                usage=TokenUsage(
                    prompt_tokens=data.get("usage", {}).get("input_tokens", 0),
                    completion_tokens=data.get("usage", {}).get("output_tokens", 0),
                    total_tokens=(data.get("usage", {}).get("input_tokens", 0)
                                  + data.get("usage", {}).get("output_tokens", 0)),
                ),
                raw=data,
                content_blocks=data.get("content", []),
            )
        except httpx.HTTPError as e:
            raise ProviderNotAvailableError("anthropic", str(e))

    async def chat_stream(self, messages) -> AsyncIterator[str]:
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": 4096,
            "stream": True,
        }
        try:
            async with self.client.stream("POST", "/v1/messages", json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        import json
                        try:
                            data = json.loads(line[6:])
                            if data.get("type") == "content_block_delta":
                                yield data.get("delta", {}).get("text", "")
                        except (json.JSONDecodeError, KeyError):
                            continue
        except httpx.HTTPError as e:
            raise ProviderNotAvailableError("anthropic", str(e))

    async def vision_analyze(self, image_data, prompt) -> str:
        import base64
        image_b64 = base64.b64encode(image_data).decode()
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image", "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": image_b64,
                }},
            ]}],
            "max_tokens": 1024,
        }
        try:
            resp = await self.client.post("/v1/messages", json=payload)
            resp.raise_for_status()
            data = resp.json()
            for block in data.get("content", []):
                if block.get("type") == "text":
                    return block.get("text", "")
            return ""
        except httpx.HTTPError as e:
            raise ProviderNotAvailableError("anthropic", str(e))

    async def transcribe_audio(self, audio_data, **kwargs) -> str:
        return ""  # Anthropic doesn't support STT

    async def health_check(self) -> bool:
        try:
            resp = await self.client.post("/v1/messages", json={
                "model": self.model,
                "max_tokens": 1,
                "messages": [{"role": "user", "content": "hi"}],
            })
            return resp.status_code == 200
        except Exception:
            return False
