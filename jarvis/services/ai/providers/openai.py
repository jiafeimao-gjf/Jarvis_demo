# jarvis/services/ai/providers/openai.py
"""OpenAI Provider Adapter"""
import os
import base64
import httpx
from typing import Optional, AsyncIterator
from jarvis.services.ai.base import AIClient, AIResponse, TokenUsage
from jarvis.services.ai.exceptions import ProviderNotAvailableError, AuthenticationError, RateLimitError
from jarvis.utils.logger import get_logger

logger = get_logger(__name__)


class OpenAIAdapter(AIClient):
    """OpenAI API adapter"""

    DEFAULT_BASE_URL = "https://api.openai.com/v1"

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
        """Lazy-loaded HTTP client with auth"""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.timeout),
                headers={"Authorization": f"Bearer {self.api_key}"}
            )
        return self._client

    async def close(self):
        """Close HTTP client"""
        if self._client:
            await self._client.aclose()
            self._client = None

    def _get_headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    async def generate(
        self,
        prompt: str,
        stream: bool = True,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        system: Optional[str] = None,
    ) -> AIResponse:
        """Generate text using chat completions"""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        return await self._chat_request(messages, stream, temperature, max_tokens)

    async def chat(
        self,
        messages: list[dict],
        stream: bool = True,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> AIResponse:
        """Chat completion"""
        return await self._chat_request(messages, stream, temperature, max_tokens)

    async def _chat_request(
        self,
        messages: list[dict],
        stream: bool,
        temperature: float,
        max_tokens: int,
    ) -> AIResponse:
        """Make chat completions request"""
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": stream,
            "temperature": temperature,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens

        try:
            response = await self.client.post("/chat/completions", json=payload)
            response.raise_for_status()
            data = response.json()

            content = data["choices"][0]["message"]["content"]
            usage_data = data.get("usage", {})

            return AIResponse(
                content=content,
                model=self.model,
                provider="openai",
                done=True,
                usage=TokenUsage(
                    prompt_tokens=usage_data.get("prompt_tokens", 0),
                    completion_tokens=usage_data.get("completion_tokens", 0),
                    total_tokens=usage_data.get("total_tokens", 0),
                ),
                raw=data
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise AuthenticationError("openai", "Invalid API key")
            elif e.response.status_code == 429:
                raise RateLimitError("openai", "Rate limit exceeded")
            raise ProviderNotAvailableError("openai", str(e))
        except httpx.HTTPError as e:
            logger.error(f"OpenAI chat error: {e}")
            raise ProviderNotAvailableError("openai", str(e))

    async def chat_stream(
        self,
        messages: list[dict],
    ) -> AsyncIterator[str]:
        """Stream chat completion tokens"""
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "temperature": 0.7,
        }

        try:
            async with self.client.stream("POST", "/chat/completions", json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        if line.strip() == "data: [DONE]":
                            break
                        try:
                            import json
                            data = json.loads(line[6:])
                            content = data.get("choices", [{}])[0].get("delta", {}).get("content", "")
                            if content:
                                yield content
                        except (json.JSONDecodeError, KeyError):
                            continue
        except httpx.HTTPError as e:
            logger.error(f"OpenAI chat stream error: {e}")
            yield f"Error: {str(e)}"

    async def vision_analyze(
        self,
        image_data: bytes,
        prompt: str,
    ) -> str:
        """Analyze image using vision model"""
        image_base64 = base64.b64encode(image_data).decode()

        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}
                }
            ]
        }]

        payload = {
            "model": self.model,
            "messages": messages,
        }

        try:
            response = await self.client.post("/chat/completions", json=payload)
            response.raise_for_status()
            data = response.json()

            return data["choices"][0]["message"]["content"]
        except httpx.HTTPError as e:
            logger.error(f"OpenAI vision error: {e}")
            raise ProviderNotAvailableError("openai", str(e))

    async def health_check(self) -> bool:
        """Check if OpenAI API is accessible"""
        try:
            response = await self.client.get("/models")
            return response.status_code == 200
        except Exception as e:
            logger.error(f"OpenAI health check failed: {e}")
            return False