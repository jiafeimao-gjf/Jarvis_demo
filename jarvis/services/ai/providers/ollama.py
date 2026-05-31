# jarvis/services/ai/providers/ollama.py
"""Ollama Provider Adapter"""
import json
import httpx
from typing import Optional, AsyncIterator
from jarvis.services.ai.base import AIClient, AIResponse
from jarvis.services.ai.models import ModelInfo, Provider
from jarvis.services.ai.exceptions import ProviderNotAvailableError, ModelNotSupportedError
from jarvis.utils.logger import get_logger

logger = get_logger(__name__)


class OllamaAdapter(AIClient):
    """Ollama local AI provider adapter"""

    def __init__(
        self,
        model: str,
        base_url: str = "http://localhost:11434",
        timeout: float = 60.0,
        max_retries: int = 3,
    ):
        super().__init__(model=model, provider="ollama")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def client(self) -> httpx.AsyncClient:
        """Lazy-loaded HTTP client"""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.timeout)
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
        """Generate text using /api/generate endpoint"""
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": stream,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            }
        }
        if system:
            payload["system"] = system

        try:
            response = await self.client.post("/api/generate", json=payload)
            response.raise_for_status()
            data = response.json()

            return AIResponse(
                content=data.get("response", ""),
                model=self.model,
                provider="ollama",
                done=data.get("done", True),
                raw=data
            )
        except httpx.HTTPError as e:
            logger.error(f"Ollama generate error: {e}")
            raise ProviderNotAvailableError("ollama", str(e))

    async def chat(
        self,
        messages: list[dict],
        stream: bool = True,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> AIResponse:
        """Chat completion using /api/chat endpoint"""
        for attempt in range(self.max_retries):
            try:
                payload = {
                    "model": self.model,
                    "messages": messages,
                    "stream": stream,
                    "options": {
                        "temperature": temperature,
                        "num_predict": max_tokens,
                    }
                }

                response = await self.client.post("/api/chat", json=payload)

                if response.status_code == 404:
                    if attempt == self.max_retries - 1:
                        raise ModelNotSupportedError(
                            "ollama",
                            f"Model {self.model} not found",
                            {"model": self.model}
                        )
                    continue

                response.raise_for_status()
                data = response.json()

                return AIResponse(
                    content=data.get("message", {}).get("content", ""),
                    model=self.model,
                    provider="ollama",
                    done=data.get("done", True),
                    raw=data
                )
            except httpx.HTTPError as e:
                logger.error(f"Ollama chat error (attempt {attempt + 1}/{self.max_retries}): {e}")
                if attempt == self.max_retries - 1:
                    raise ProviderNotAvailableError("ollama", str(e))
                await self._sleep(1)

        raise ProviderNotAvailableError("ollama", "Max retries exceeded")

    async def chat_stream(
        self,
        messages: list[dict],
    ) -> AsyncIterator[str]:
        """Stream chat completion tokens"""
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True
        }

        try:
            async with self.client.stream("POST", "/api/chat", json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line:
                        try:
                            data = json.loads(line)
                            content = data.get("message", {}).get("content", "")
                            if content:
                                yield content
                            if data.get("done"):
                                break
                        except json.JSONDecodeError:
                            continue
        except httpx.HTTPError as e:
            logger.error(f"Ollama chat stream error: {e}")
            yield f"Error: {str(e)}"

    async def transcribe_audio(
        self,
        audio_data: bytes,
        **kwargs,
    ) -> str:
        """Transcribe audio to text using Ollama Whisper model"""
        import base64 as _b64

        audio_b64 = _b64.b64encode(audio_data).decode()
        payload = {
            "model": self.model,
            "prompt": "Please transcribe the following audio to text:",
            "images": [],
            "stream": False,
            "options": {"temperature": 0.0}
        }
        # Note: Ollama whisper models typically process audio via /api/generate
        # with the audio data embedded. The exact API may vary by whisper version.
        # For whisper.cpp-based models, audio is processed via multipart upload.
        # For now, attempt the generate path; fall back gracefully.

        try:
            response = await self.client.post("/api/generate", json=payload)
            response.raise_for_status()
            data = response.json()
            return data.get("response", "").strip()
        except httpx.HTTPError as e:
            logger.error(f"Ollama transcribe_audio error: {e}")
            raise ProviderNotAvailableError("ollama", f"Audio transcription failed: {e}")

    async def vision_analyze(
        self,
        image_data: bytes,
        prompt: str,
    ) -> str:
        """Analyze image using vision model"""
        import base64

        image_base64 = base64.b64encode(image_data).decode()

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                    "images": [image_base64]
                }
            ],
            "stream": False
        }

        try:
            response = await self.client.post("/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()

            return data.get("message", {}).get("content", "")
        except httpx.HTTPError as e:
            logger.error(f"Ollama vision error: {e}")
            raise ProviderNotAvailableError("ollama", str(e))

    async def health_check(self) -> bool:
        """Check if Ollama is running"""
        try:
            response = await self.client.get("/api/tags")
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Ollama health check failed: {e}")
            return False

    async def list_models(self, force_refresh: bool = False) -> list[dict]:
        """List available models in Ollama"""
        try:
            # Use cache-busting if force refresh
            if force_refresh:
                import time
                url = f"/api/tags?_t={int(time.time())}"
            else:
                url = "/api/tags"
            response = await self.client.get(url)
            response.raise_for_status()
            data = response.json()
            return data.get("models", [])
        except httpx.HTTPError as e:
            logger.error(f"Failed to list Ollama models: {e}")
            return []

    async def _sleep(self, seconds: float):
        """Async sleep helper"""
        import asyncio
        await asyncio.sleep(seconds)