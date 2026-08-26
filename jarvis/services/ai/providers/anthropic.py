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
        base_url: str = "https://api.anthropic.com",
        timeout: float = 60.0,
    ):
        super().__init__(model=model, provider="anthropic")
        self.provider_protocol = "anthropic"
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
        }
        from jarvis.core.tool_registry import tool_registry
        tools = tool_registry.build_anthropic_tools()
        if tools:
            payload["tools"] = tools
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
                provider_protocol=self.provider_protocol,
            )
        except httpx.HTTPError as e:
            # Log response body for debugging
            body = ""
            try:
                body = getattr(e, "response", None)
                if body and hasattr(body, "text"):
                    body = body.text[:500]
            except Exception:
                pass
            logger.error(
                f"[Anthropic] _messages HTTP error: {e}"
                + (f" | body: {body}" if body else "")
            )
            raise ProviderNotAvailableError("anthropic", str(e))

    async def chat_stream_full(self, messages) -> AsyncIterator[dict]:
        """Streaming with structured events: thinking + text + tool_use."""
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
        import json as _json
        current_block_type = None
        tool_name = ""
        tool_id = ""
        tool_input_parts = []

        try:
            async with self.client.stream("POST", "/v1/messages", json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        try:
                            data = _json.loads(line[6:])
                        except _json.JSONDecodeError:
                            continue

                        evt_type = data.get("type", "")

                        if evt_type == "message_start":
                            yield {"type": "message_start", "content": ""}

                        elif evt_type == "content_block_start":
                            block = data.get("content_block", {})
                            block_type = block.get("type", "")
                            current_block_type = block_type

                            if block_type == "thinking":
                                yield {"type": "thinking_start", "content": ""}
                            elif block_type == "text":
                                yield {"type": "text_start", "content": ""}
                            elif block_type == "tool_use":
                                tool_name = block.get("name", "")
                                tool_id = block.get("id", "")
                                tool_input_parts = []
                                yield {
                                    "type": "tool_use_start",
                                    "name": tool_name,
                                    "id": tool_id,
                                }

                        elif evt_type == "content_block_delta":
                            delta = data.get("delta", {})
                            delta_type = delta.get("type", "")

                            if current_block_type == "thinking" and delta_type == "thinking_delta":
                                yield {"type": "thinking", "content": delta.get("thinking", "")}
                            elif current_block_type == "text" and delta_type == "text_delta":
                                yield {"type": "text", "content": delta.get("text", "")}
                            elif current_block_type == "tool_use" and delta_type == "input_json_delta":
                                chunk = delta.get("partial_json", "")
                                tool_input_parts.append(chunk)
                                yield {"type": "tool_use_delta", "partial_json": chunk}

                        elif evt_type == "content_block_stop":
                            if current_block_type == "thinking":
                                yield {"type": "thinking_end", "content": ""}
                            elif current_block_type == "text":
                                yield {"type": "text_end", "content": ""}
                            elif current_block_type == "tool_use":
                                full_json = "".join(tool_input_parts)
                                try:
                                    input_data = _json.loads(full_json)
                                except _json.JSONDecodeError:
                                    logger.warning(f"[Anthropic] failed to parse tool_use input: {full_json[:200]}")
                                    input_data = {}
                                yield {
                                    "type": "tool_use_end",
                                    "name": tool_name,
                                    "id": tool_id,
                                    "input": input_data,
                                }
                            current_block_type = None

                        elif evt_type == "message_delta":
                            yield {"type": "message_delta", "content": ""}

                        elif evt_type == "message_stop":
                            yield {"type": "message_stop", "content": ""}

        except httpx.HTTPError as e:
            raise ProviderNotAvailableError("anthropic", str(e))

    async def chat_stream(self, messages) -> AsyncIterator[str]:
        """Streaming plain text (for backward compat)."""
        async for event in self.chat_stream_full(messages):
            evt_type = event.get("type", "")
            if evt_type in ("thinking", "text"):
                yield event["content"]

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
