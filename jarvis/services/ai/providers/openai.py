# jarvis/services/ai/providers/openai.py
"""OpenAI Provider Adapter"""
import os
import httpx
from typing import Optional, AsyncIterator
from jarvis.services.ai.base import AIClient, AIResponse, TokenUsage
from jarvis.services.ai.exceptions import ProviderNotAvailableError, AuthenticationError
from jarvis.utils.logger import get_logger

logger = get_logger(__name__)


class OpenAIAdapter(AIClient):
    """OpenAI API adapter — implements /v1/chat/completions"""

    def __init__(
        self,
        model: str,
        api_key: Optional[str] = None,
        base_url: str = "https://api.openai.com/v1",
        timeout: float = 60.0,
    ):
        super().__init__(model=model, provider="openai")
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
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
                    "Authorization": f"Bearer {self.api_key}",
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
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return await self.chat(messages, stream, temperature, max_tokens)

    async def chat(self, messages, stream=True, temperature=0.7,
                   max_tokens=2048) -> AIResponse:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        try:
            resp = await self.client.post("/v1/chat/completions", json=payload)
            if resp.status_code == 401:
                raise AuthenticationError("openai", "Invalid API key")
            resp.raise_for_status()
            data = resp.json()
            choice = data["choices"][0]
            return AIResponse(
                content=choice["message"]["content"],
                model=self.model,
                provider="openai",
                usage=TokenUsage(**data.get("usage", {})),
                raw=data,
            )
        except httpx.HTTPError as e:
            raise ProviderNotAvailableError("openai", str(e))

    async def chat_stream(self, messages) -> AsyncIterator[str]:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 4096,
            "stream": True,
        }
        try:
            async with self.client.stream("POST", "/v1/chat/completions", json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line.startswith("data: ") and line.strip() != "data: [DONE]":
                        import json
                        try:
                            data = json.loads(line[6:])
                            delta = data["choices"][0].get("delta", {})
                            if "content" in delta:
                                yield delta["content"]
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue
        except httpx.HTTPError as e:
            raise ProviderNotAvailableError("openai", str(e))

    async def vision_analyze(self, image_data, prompt) -> str:
        import base64
        image_b64 = base64.b64encode(image_data).decode()
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
            ]}],
            "max_tokens": 1024,
        }
        try:
            resp = await self.client.post("/v1/chat/completions", json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except httpx.HTTPError as e:
            raise ProviderNotAvailableError("openai", str(e))

    async def transcribe_audio(self, audio_data, **kwargs) -> str:
        """OpenAI doesn't support transcribe_audio in this adapter"""
        return ""

    async def health_check(self) -> bool:
        try:
            resp = await self.client.get("/v1/models")
            return resp.status_code == 200
        except Exception:
            return False
