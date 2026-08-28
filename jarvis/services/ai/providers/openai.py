# jarvis/services/ai/providers/openai.py
"""OpenAI Provider Adapter — implements /v1/chat/completions (PR3).

PR3 重要变更:
  - provider_protocol = "openai"
  - chat() 返回 AIResponse 时把 message.tool_calls 转换成 content_blocks 形态
    (与 Anthropic 的 tool_use 块同构, 供 AgentLoopRunner 统一消费)
  - chat_stream_full() 解析 delta.tool_calls SSE → tool_use_start/delta/end 事件
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
    """把 OpenAI 响应里的 message.tool_calls 转成 Anthropic 形态的 tool_use blocks.

    OpenAI 形态:
      [{"id": "call_xxx", "type": "function",
        "function": {"name": "bash", "arguments": "{\"command\":\"ls\"}"}}]

    输出 (Anthropic 形态):
      [{"type": "tool_use", "id": "call_xxx", "name": "bash",
        "input": {"command": "ls"}}]
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
            logger.warning(f"[OpenAI] tool_call.arguments 不是合法 JSON: {args_raw[:200]}")
            inp = {}
        blocks.append({
            "type": "tool_use",
            "id": tc.get("id", ""),
            "name": name,
            "input": inp,
        })
    return blocks


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
        self.provider_protocol = "openai"
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
                   max_tokens=2048, *, call_id=None) -> AIResponse:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        # 注入工具 schema (OpenAI 形态)
        from jarvis.core.tool_registry import tool_registry
        tools = tool_registry.build_openai_tools()
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        # ── raw HTTP body 捕获 ──
        from jarvis.services.ai.call_logger import enrich_raw_body
        if call_id is not None:
            enrich_raw_body(call_id, raw_request=payload)
        try:
            resp = await self.client.post("/v1/chat/completions", json=payload)
            if resp.status_code == 401:
                raise AuthenticationError("openai", "Invalid API key")
            resp.raise_for_status()
            data = resp.json()
            if call_id is not None:
                enrich_raw_body(call_id, raw_response=data)
            choice = data["choices"][0]
            message = choice.get("message", {})
            content = message.get("content", "") or ""
            tool_calls_raw = message.get("tool_calls") or []
            content_blocks = _openai_tool_calls_to_blocks(tool_calls_raw)
            return AIResponse(
                content=content,
                model=self.model,
                provider="openai",
                usage=TokenUsage(**data.get("usage", {})) if data.get("usage") else None,
                raw=data,
                content_blocks=content_blocks or None,
                provider_protocol=self.provider_protocol,
            )
        except httpx.HTTPError as e:
            raise ProviderNotAvailableError("openai", str(e))

    async def chat_stream(self, messages, *, call_id=None) -> AsyncIterator[str]:
        """Backward-compat: 仅 yield 文本 token. 推荐用 chat_stream_full."""
        async for event in self.chat_stream_full(messages, call_id=call_id):
            if event.get("type") == "text":
                yield event["content"]

    async def chat_stream_full(self, messages, *, call_id=None) -> AsyncIterator[dict]:
        """Streaming + tool_calls delta 拼装.

        call_id: 由 router 显式传入, 用于把 raw_request + raw_stream_events 写回日志.

        OpenAI delta 形态:
          - delta.content: 文本增量 (str)
          - delta.tool_calls: 列表, 每个元素含
              - index: 同一调用跨多个 chunk 的拼接索引
              - id:   第一次出现时携带
              - function.name: 第一次出现时携带
              - function.arguments: 增量 JSON 字符串
        """
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

        # 按 index 累积 tool_call 增量
        # tc_buf[index] = {"id": "", "name": "", "args_parts": []}
        tc_buf: dict[int, dict] = {}
        # 文本流状态
        in_text = False
        # finish_reason
        finish_reason = None

        # ── raw HTTP body 捕获 ──
        from jarvis.services.ai.call_logger import enrich_raw_body
        if call_id is not None:
            enrich_raw_body(call_id, raw_request=payload)
        raw_sse_chunks: list[dict] = []

        try:
            async with self.client.stream(
                "POST", "/v1/chat/completions", json=payload
            ) as resp:
                if resp.status_code == 401:
                    raise AuthenticationError("openai", "Invalid API key")
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
                    if call_id is not None:
                        raw_sse_chunks.append(data)

                    choice = (data.get("choices") or [{}])[0]
                    delta = choice.get("delta", {}) or {}
                    finish_reason = choice.get("finish_reason") or finish_reason

                    # 文本增量
                    text_chunk = delta.get("content")
                    if text_chunk:
                        if not in_text:
                            yield {"type": "text_start", "content": ""}
                            in_text = True
                        yield {"type": "text", "content": text_chunk}

                    # tool_calls 增量
                    for tc in delta.get("tool_calls") or []:
                        if not isinstance(tc, dict):
                            continue
                        idx = tc.get("index", 0)
                        if idx not in tc_buf:
                            tc_buf[idx] = {"id": "", "name": "", "args_parts": []}
                            # 新工具开始
                            tc_id = tc.get("id", "")
                            fn = tc.get("function") or {}
                            tc_buf[idx]["id"] = tc_id
                            tc_buf[idx]["name"] = fn.get("name", "")
                            yield {
                                "type": "tool_use_start",
                                "name": tc_buf[idx]["name"],
                                "id": tc_id,
                            }
                        # arguments 增量
                        fn_delta = tc.get("function") or {}
                        args_delta = fn_delta.get("arguments")
                        if args_delta:
                            tc_buf[idx]["args_parts"].append(args_delta)
                            yield {
                                "type": "tool_use_delta",
                                "partial_json": args_delta,
                            }
                        # 极少数 SDK 会把 name 放在后续 chunk 里, 兼容
                        if fn_delta.get("name") and not tc_buf[idx]["name"]:
                            tc_buf[idx]["name"] = fn_delta["name"]

            # 流结束 — flush text_end + 拼装所有 tool_use_end
            if in_text:
                yield {"type": "text_end", "content": ""}
            for idx in sorted(tc_buf.keys()):
                entry = tc_buf[idx]
                full_json = "".join(entry["args_parts"])
                try:
                    input_data = json.loads(full_json) if full_json else {}
                except json.JSONDecodeError:
                    logger.warning(
                        f"[OpenAI] tool_call[{idx}] arguments 拼装失败: {full_json[:200]}"
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

            # 流结束 — 把所有 SSE chunk 一次性写入日志
            if call_id is not None and raw_sse_chunks:
                enrich_raw_body(call_id, raw_stream_events=raw_sse_chunks)

        except httpx.HTTPError as e:
            if call_id is not None and raw_sse_chunks:
                enrich_raw_body(call_id, raw_stream_events=raw_sse_chunks)
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
