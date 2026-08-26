# jarvis/services/ai/providers/ollama.py
"""Ollama Provider Adapter"""
import json
import os
import tempfile
import httpx
from typing import Optional, AsyncIterator
from jarvis.services.ai.base import AIClient, AIResponse
from jarvis.services.ai.models import ModelInfo, Provider
from jarvis.services.ai.exceptions import ProviderNotAvailableError, ModelNotSupportedError
from jarvis.utils.logger import get_logger

logger = get_logger(__name__)

# Lazily-load whisper model (global, loaded once on first STT call)
_whisper_model = None
_WHISPER_SIZE = "base"  # tiny/base/small/medium/large


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
        self.provider_protocol = "anthropic"
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def client(self) -> httpx.AsyncClient:
        """Lazy-loaded HTTP client — connect=10s, read=self.timeout"""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(10.0, read=self.timeout, write=30.0, pool=10.0)
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
        """Generate text — legacy, delegates to /v1/messages"""
        messages = [{"role": "user", "content": prompt}]
        return await self.chat(messages, stream, temperature, max_tokens)

    async def chat(
        self,
        messages: list[dict],
        stream: bool = True,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> AIResponse:
        """Chat completion using Anthropic-compatible /v1/messages"""
        for attempt in range(self.max_retries):
            try:
                payload = {
                    "model": self.model,
                    "messages": messages,
                    "max_tokens": max_tokens or 4096,
                    "temperature": temperature,
                    "stream": False,
                }
                # Include tools for /v1/messages
                from jarvis.core.tool_registry import tool_registry
                tools = tool_registry.build_anthropic_tools()
                if tools:
                    payload["tools"] = tools

                response = await self.client.post("/v1/messages", json=payload)

                if response.status_code == 404:
                    if attempt == self.max_retries - 1:
                        raise ModelNotSupportedError(
                            "ollama", f"Model {self.model} not found",
                            {"model": self.model}
                        )
                    await self._sleep(1)
                    continue

                response.raise_for_status()
                data = response.json()

                # /v1/messages returns content blocks: text, thinking, tool_use
                content = ""
                thinking = ""
                content_blocks = data.get("content", [])
                for block in content_blocks:
                    if block.get("type") == "text":
                        content = block.get("text", "")
                    elif block.get("type") == "thinking":
                        thinking = block.get("thinking", "")

                return AIResponse(
                    content=content,
                    thinking=thinking,
                    model=self.model,
                    provider="ollama",
                    done=True,
                    raw=data,
                    content_blocks=content_blocks,
                    provider_protocol=self.provider_protocol,
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
        """Stream chat via /v1/messages (SSE with Anthropic format)"""
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": 4096,
            "stream": True,
        }

        try:
            async with self.client.stream(
                "POST", "/v1/messages", json=payload
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("data: ") and line.strip() != "data: [DONE]":
                        try:
                            data = json.loads(line[6:])
                            if data.get("type") == "content_block_delta":
                                delta = data.get("delta", {})
                                if "text" in delta:
                                    yield delta["text"]
                        except (json.JSONDecodeError, KeyError):
                            continue
        except httpx.HTTPError as e:
            logger.error(f"Ollama chat stream error: {e}")
            yield f"Error: {str(e)}"

    async def chat_stream_full(
        self,
        messages: list[dict],
    ) -> AsyncIterator[dict]:
        """Stream chat via /v1/messages with structured events.

        Yields typed dicts so the caller can stream text/thinking to the
        frontend while simultaneously watching for tool_use blocks — no more
        waiting for the full response before showing the first token.
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": 4096,
            "stream": True,
        }
        from jarvis.core.tool_registry import tool_registry
        tools = tool_registry.build_anthropic_tools()
        if tools:
            payload["tools"] = tools

        try:
            async with self.client.stream(
                "POST", "/v1/messages", json=payload
            ) as response:
                response.raise_for_status()

                current_block_type: str | None = None
                tool_name: str = ""
                tool_id: str = ""
                tool_input_parts: list[str] = []

                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:].strip()
                    if not data_str or data_str == "[DONE]":
                        continue

                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    event_type = data.get("type", "")

                    if event_type == "content_block_start":
                        block = data.get("content_block", {})
                        block_type = block.get("type", "")
                        current_block_type = block_type

                        if block_type == "text":
                            yield {"type": "text_start"}
                        elif block_type == "thinking":
                            yield {"type": "thinking_start"}
                        elif block_type == "tool_use":
                            tool_name = block.get("name", "")
                            tool_id = block.get("id", "")
                            tool_input_parts = []
                            yield {
                                "type": "tool_use_start",
                                "name": tool_name,
                                "id": tool_id,
                            }

                    elif event_type == "content_block_delta":
                        delta = data.get("delta", {})

                        if current_block_type == "text" and "text" in delta:
                            yield {"type": "text", "content": delta["text"]}
                        elif current_block_type == "thinking" and "thinking" in delta:
                            yield {"type": "thinking", "content": delta["thinking"]}
                        elif current_block_type == "tool_use" and "partial_json" in delta:
                            chunk = delta["partial_json"]
                            tool_input_parts.append(chunk)
                            yield {"type": "tool_use_delta", "partial_json": chunk}

                    elif event_type == "content_block_stop":
                        if current_block_type == "thinking":
                            yield {"type": "thinking_end"}
                        elif current_block_type == "tool_use":
                            # Parse accumulated partial JSON
                            full_json = "".join(tool_input_parts)
                            try:
                                input_data = json.loads(full_json)
                            except json.JSONDecodeError:
                                logger.warning(
                                    f"[Ollama] failed to parse tool_use input: {full_json[:200]}"
                                )
                                input_data = {}
                            yield {
                                "type": "tool_use_end",
                                "name": tool_name,
                                "id": tool_id,
                                "input": input_data,
                            }
                        current_block_type = None

                    elif event_type == "message_delta":
                        yield {
                            "type": "message_delta",
                            "stop_reason": data.get("delta", {}).get("stop_reason", ""),
                        }

                    elif event_type == "message_stop":
                        yield {"type": "message_stop"}

        except httpx.HTTPError as e:
            logger.error(f"Ollama chat_stream_full error: {e}")
            yield {"type": "error", "content": str(e)}

    async def transcribe_audio(
        self,
        audio_data: bytes,
        **kwargs,
    ) -> str:
        """Transcribe audio using local openai-whisper model.

        Frontend records audio/webm (Opus) → ffmpeg decodes to 16kHz mono
        WAV → whisper transcribes.
        """
        import asyncio

        global _whisper_model

        # Lazy-load whisper model (once)
        if _whisper_model is None:
            import whisper
            _whisper_model = whisper.load_model(_WHISPER_SIZE)
            logger.info(f"[whisper] loaded model: {_WHISPER_SIZE}")

        raw_path = None
        wav_path = None
        try:
            # Write raw audio (WebM/Opus) to temp file
            with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f:
                f.write(audio_data)
                raw_path = f.name

            # Decode to 16kHz mono WAV via ffmpeg
            wav_path = raw_path + ".wav"
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-y", "-i", raw_path,
                "-ar", "16000", "-ac", "1", "-f", "wav", wav_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            if proc.returncode != 0 or not os.path.exists(wav_path):
                err = stderr.decode()[:200] if stderr else "unknown"
                raise RuntimeError(f"ffmpeg decode failed: {err}")

            wav_size = os.path.getsize(wav_path)
            logger.info(
                f"[whisper] {len(audio_data)} bytes WebM → {wav_size} bytes WAV"
            )

            # Run whisper in thread pool (CPU-bound)
            result = await asyncio.to_thread(
                _whisper_model.transcribe,
                wav_path,
                language="zh",
                fp16=False,
            )
            text = result["text"].strip()
            logger.info(f"[whisper] result ({len(text)} chars): {text[:120]}")
            return text

        except Exception as e:
            logger.error(f"[whisper] error: {type(e).__name__}: {e}")
            raise ProviderNotAvailableError("ollama", f"Whisper error: {e}")
        finally:
            for p in [raw_path, wav_path]:
                if p and os.path.exists(p):
                    try:
                        os.unlink(p)
                    except OSError:
                        pass

    async def vision_analyze(
        self,
        image_data: bytes,
        prompt: str,
    ) -> str:
        """Analyze image using /v1/messages (Anthropic vision format)"""
        import base64, time

        image_base64 = base64.b64encode(image_data).decode()

        payload = {
            "model": self.model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image", "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": image_base64,
                    }},
                ],
            }],
            "max_tokens": 1024,
            "stream": False,
        }

        logger.info(
            f"[Ollama] vision request: model={self.model}, "
            f"image={len(image_data)} bytes"
        )

        try:
            t0 = time.time()
            # Vision can be slow — per-request timeout (read=180s)
            response = await self.client.post(
                "/v1/messages", json=payload,
                timeout=httpx.Timeout(10.0, read=180.0, write=30.0),
            )
            response.raise_for_status()
            data = response.json()

            content = ""
            for block in data.get("content", []):
                if block.get("type") == "text":
                    content = block.get("text", "")
                    break

            elapsed = (time.time() - t0) * 1000
            logger.info(
                f"[Ollama] vision response: status={response.status_code}, "
                f"elapsed={elapsed:.0f}ms, result_len={len(content)}"
            )
            return content
        except httpx.HTTPError as e:
            logger.error(f"[Ollama] vision error: {e}")
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