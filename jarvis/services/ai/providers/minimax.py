# jarvis/services/ai/providers/minimax.py
"""MiniMax Provider Adapter — OpenAI-compatible /v1/chat/completions (PR3).

实现与 OpenAI 完全相同的 tool-calls 协议, 因为 MiniMax API 是 OpenAI 兼容的.
仅 provider_protocol 字段区分 (用于日志 + 诊断).
"""
import json
import os
import httpx
from typing import Optional, AsyncIterator
from jarvis.services.ai.base import AIClient, AIResponse, TokenUsage
from jarvis.services.ai.exceptions import ProviderNotAvailableError, AuthenticationError
from jarvis.utils.logger import get_logger

logger = get_logger(__name__)


def _openai_tool_calls_to_blocks(tool_calls: list[dict]) -> list[dict]:
    """把 OpenAI 响应里的 message.tool_calls 转成 Anthropic tool_use blocks.

    与 openai.py 同源逻辑, 这里独立一份避免互相 import 的循环依赖.
    """
    blocks = []
    for tc in tool_calls or []:
        if not isinstance(tc, dict):
            continue
        fn = tc.get("function") or {}
        name = fn.get("name", "")
        args_raw = fn.get("arguments", "") or "{}"
        try:
            inp = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw or {})
        except json.JSONDecodeError:
            logger.warning(f"[MiniMax] tool_call.arguments 不是合法 JSON: {args_raw[:200]}")
            inp = {}
        blocks.append({
            "type": "tool_use",
            "id": tc.get("id", ""),
            "name": name,
            "input": inp,
        })
    return blocks


class MiniMaxAdapter(AIClient):
    """MiniMax API adapter — OpenAI-compatible /v1/chat/completions"""

    def __init__(
        self,
        model: str,
        api_key: Optional[str] = None,
        base_url: str = "https://api.minimax.chat",
        timeout: float = 60.0,
    ):
        super().__init__(model=model, provider="minimax")
        self.provider_protocol = "openai"
        self.api_key = api_key or os.getenv("MINIMAX_API_KEY", "")
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
        from jarvis.core.tool_registry import tool_registry
        tools = tool_registry.build_openai_tools()
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        try:
            resp = await self.client.post("/v1/chat/completions", json=payload)
            if resp.status_code == 401:
                raise AuthenticationError("minimax", "Invalid API key")
            resp.raise_for_status()
            data = resp.json()
            choice = data["choices"][0]
            message = choice.get("message", {})
            content = message.get("content", "") or ""
            tool_calls_raw = message.get("tool_calls") or []
            content_blocks = _openai_tool_calls_to_blocks(tool_calls_raw)
            return AIResponse(
                content=content,
                model=self.model,
                provider="minimax",
                usage=TokenUsage(**data.get("usage", {})) if data.get("usage") else None,
                raw=data,
                content_blocks=content_blocks or None,
                provider_protocol=self.provider_protocol,
            )
        except httpx.HTTPError as e:
            raise ProviderNotAvailableError("minimax", str(e))

    async def chat_stream(self, messages) -> AsyncIterator[str]:
        """Backward-compat: 仅 yield 文本 token."""
        async for event in self.chat_stream_full(messages):
            if event.get("type") == "text":
                yield event["content"]

    async def chat_stream_full(self, messages) -> AsyncIterator[dict]:
        """Streaming + tool_calls delta 拼装 — 与 OpenAI 同协议."""
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 4096,
            "stream": True,
        }
        from jarvis.core.tool_registry import tool_registry
        tools = tool_registry.build_openai_tools()
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        tc_buf: dict[int, dict] = {}
        in_text = False
        finish_reason = None

        try:
            async with self.client.stream(
                "POST", "/v1/chat/completions", json=payload
            ) as resp:
                if resp.status_code == 401:
                    raise AuthenticationError("minimax", "Invalid API key")
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    payload_str = line[len("data: "):].strip()
                    if payload_str == "[DONE]":
                        break
                    try:
                        data = json.loads(payload_str)
                    except json.JSONDecodeError:
                        continue

                    choice = (data.get("choices") or [{}])[0]
                    delta = choice.get("delta", {}) or {}
                    finish_reason = choice.get("finish_reason") or finish_reason

                    text_chunk = delta.get("content")
                    if text_chunk:
                        if not in_text:
                            yield {"type": "text_start", "content": ""}
                            in_text = True
                        yield {"type": "text", "content": text_chunk}

                    for tc in delta.get("tool_calls") or []:
                        if not isinstance(tc, dict):
                            continue
                        idx = tc.get("index", 0)
                        if idx not in tc_buf:
                            tc_buf[idx] = {"id": "", "name": "", "args_parts": []}
                            tc_id = tc.get("id", "")
                            fn = tc.get("function") or {}
                            tc_buf[idx]["id"] = tc_id
                            tc_buf[idx]["name"] = fn.get("name", "")
                            yield {
                                "type": "tool_use_start",
                                "name": tc_buf[idx]["name"],
                                "id": tc_id,
                            }
                        fn_delta = tc.get("function") or {}
                        args_delta = fn_delta.get("arguments")
                        if args_delta:
                            tc_buf[idx]["args_parts"].append(args_delta)
                            yield {
                                "type": "tool_use_delta",
                                "partial_json": args_delta,
                            }
                        if fn_delta.get("name") and not tc_buf[idx]["name"]:
                            tc_buf[idx]["name"] = fn_delta["name"]

            if in_text:
                yield {"type": "text_end", "content": ""}
            for idx in sorted(tc_buf.keys()):
                entry = tc_buf[idx]
                full_json = "".join(entry["args_parts"])
                try:
                    input_data = json.loads(full_json) if full_json else {}
                except json.JSONDecodeError:
                    logger.warning(
                        f"[MiniMax] tool_call[{idx}] arguments 拼装失败: {full_json[:200]}"
                    )
                    input_data = {}
                yield {
                    "type": "tool_use_end",
                    "name": entry["name"],
                    "id": entry["id"],
                    "input": input_data,
                }

            yield {
                "type": "message_delta",
                "content": "",
                "stop_reason": finish_reason or "",
            }
            yield {"type": "message_stop", "content": ""}

        except httpx.HTTPError as e:
            raise ProviderNotAvailableError("minimax", str(e))

    async def vision_analyze(self, image_data, prompt) -> str:
        # MiniMax may support vision; fall back to not-available
        raise ProviderNotAvailableError("minimax", "vision_analyze not supported")

    async def transcribe_audio(self, audio_data, **kwargs) -> str:
        return ""

    async def health_check(self) -> bool:
        try:
            resp = await self.client.get("/v1/models")
            return resp.status_code == 200
        except Exception:
            return False
