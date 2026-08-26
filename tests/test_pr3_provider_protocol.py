# tests/test_pr3_provider_protocol.py
"""PR3 测试: provider_protocol 分发 — OpenAI / MiniMax 按 OpenAI 协议
   (tool_calls + role=tool), Ollama / Anthropic 走 Anthropic 协议
   (tool_use blocks + user tool_result)."""
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from jarvis.services.ai.base import AIResponse
from jarvis.services.ai.providers.openai import (
    OpenAIAdapter,
    _openai_tool_calls_to_blocks,
)
from jarvis.services.ai.providers.minimax import (
    MiniMaxAdapter,
)


# ── OpenAI tool_calls → Anthropic 形态 blocks 转换 ────────────────────


class TestOpenAIToolCallsToBlocks:
    """_openai_tool_calls_to_blocks 转换函数 — 纯函数, 不需要 LLM."""

    def test_basic_tool_call(self):
        """基本 tool_call 转换."""
        tcs = [{
            "id": "call_abc",
            "type": "function",
            "function": {
                "name": "bash",
                "arguments": json.dumps({"command": "ls"}),
            },
        }]
        blocks = _openai_tool_calls_to_blocks(tcs)
        assert len(blocks) == 1
        b = blocks[0]
        assert b["type"] == "tool_use"
        assert b["id"] == "call_abc"
        assert b["name"] == "bash"
        assert b["input"] == {"command": "ls"}

    def test_multiple_tool_calls(self):
        """多个 tool_call 保留顺序."""
        tcs = [
            {"id": "1", "function": {"name": "bash", "arguments": "{}"}},
            {"id": "2", "function": {"name": "file", "arguments": "{}"}},
        ]
        blocks = _openai_tool_calls_to_blocks(tcs)
        assert [b["id"] for b in blocks] == ["1", "2"]

    def test_invalid_json_arguments(self):
        """arguments 不是合法 JSON 时, input 降级为空 dict."""
        tcs = [{
            "id": "x", "function": {"name": "bash", "arguments": "{invalid"}
        }]
        blocks = _openai_tool_calls_to_blocks(tcs)
        assert blocks[0]["input"] == {}

    def test_dict_arguments(self):
        """arguments 已经是 dict (部分 SDK 形态)."""
        tcs = [{
            "id": "x",
            "function": {"name": "bash", "arguments": {"command": "ls"}},
        }]
        blocks = _openai_tool_calls_to_blocks(tcs)
        assert blocks[0]["input"] == {"command": "ls"}

    def test_empty_list(self):
        assert _openai_tool_calls_to_blocks([]) == []

    def test_none(self):
        assert _openai_tool_calls_to_blocks(None) == []


# ── Adapter provider_protocol 字段 ────────────────────────────────────


class TestAdapterProviderProtocol:
    """每个 adapter 都该设置 provider_protocol."""

    def test_openai_protocol(self):
        a = OpenAIAdapter(model="gpt-4o-mini", api_key="dummy")
        assert a.provider_protocol == "openai"

    def test_minimax_protocol(self):
        a = MiniMaxAdapter(model="MiniMax-Text-01", api_key="dummy")
        assert a.provider_protocol == "openai"

    def test_ai_response_provider_protocol_field_exists(self):
        """AIResponse.provider_protocol 字段已添加."""
        r = AIResponse(
            content="hi", model="x", provider="openai",
            provider_protocol="openai",
        )
        assert r.provider_protocol == "openai"

    def test_ai_response_provider_protocol_default_none(self):
        """未传时, provider_protocol 默认 None (向后兼容)."""
        r = AIResponse(content="hi", model="x", provider="x")
        assert r.provider_protocol is None


# ── ChatEngine._resolve_provider_protocol ─────────────────────────────


class TestChatEngineResolveProviderProtocol:
    """ChatEngine 动态切 provider_protocol by instance.type."""

    def test_ollama_returns_anthropic(self):
        from jarvis.core.chat_engine import ChatEngine
        with patch("jarvis.core.chat_engine.memory_store"):
            engine = ChatEngine()
        inst = MagicMock()
        inst.type = "ollama"
        assert engine._resolve_provider_protocol(inst) == "anthropic"

    def test_anthropic_returns_anthropic(self):
        from jarvis.core.chat_engine import ChatEngine
        with patch("jarvis.core.chat_engine.memory_store"):
            engine = ChatEngine()
        inst = MagicMock()
        inst.type = "anthropic"
        assert engine._resolve_provider_protocol(inst) == "anthropic"

    def test_openai_returns_openai(self):
        from jarvis.core.chat_engine import ChatEngine
        with patch("jarvis.core.chat_engine.memory_store"):
            engine = ChatEngine()
        inst = MagicMock()
        inst.type = "openai"
        assert engine._resolve_provider_protocol(inst) == "openai"

    def test_minimax_returns_openai(self):
        from jarvis.core.chat_engine import ChatEngine
        with patch("jarvis.core.chat_engine.memory_store"):
            engine = ChatEngine()
        inst = MagicMock()
        inst.type = "minimax"
        assert engine._resolve_provider_protocol(inst) == "openai"

    def test_none_instance_returns_anthropic(self):
        from jarvis.core.chat_engine import ChatEngine
        with patch("jarvis.core.chat_engine.memory_store"):
            engine = ChatEngine()
        assert engine._resolve_provider_protocol(None) == "anthropic"


# ── AgentLoopRunner OpenAI 路径: assistant turn + tool_result 形态 ──


class TestAgentLoopOpenAIProtocol:
    """PR3: provider_protocol=openai 时, assistant turn / tool_result 用 OpenAI 形态."""

    @pytest.fixture
    def runner(self):
        from jarvis.core.agent_loop import AgentLoopRunner, AgentLoopConfig
        return AgentLoopRunner(
            config=AgentLoopConfig(
                max_iterations=4,
                provider_protocol="openai",
                parallel_tool_exec=False,    # 测试简单化
                inject_iteration_hint=False,
                inject_stop_hint_on_max=False,
            ),
            task_executor=MagicMock(),
            tool_parser=MagicMock(),
        )

    def test_assistant_turn_openai_shape(self, runner):
        """Anthropic blocks → OpenAI assistant turn (tool_calls + content)."""
        blocks = [
            {"type": "text", "text": "让我读文件"},
            {"type": "thinking", "thinking": "用户想知道 x.txt"},
            {"type": "tool_use", "id": "call_xyz", "name": "file",
             "input": {"action": "read", "path": "x.txt"}},
        ]
        msg = runner._build_assistant_turn(blocks, "")
        assert msg["role"] == "assistant"
        # content 应含 text + thinking (拼接, thinking 加 [思考] 前缀)
        assert "让我读文件" in (msg["content"] or "")
        assert "[思考]" in (msg["content"] or "")
        # tool_calls 应转换
        assert "tool_calls" in msg
        assert len(msg["tool_calls"]) == 1
        tc = msg["tool_calls"][0]
        assert tc["id"] == "call_xyz"
        assert tc["type"] == "function"
        assert tc["function"]["name"] == "file"
        # arguments 是 JSON 字符串
        args = json.loads(tc["function"]["arguments"])
        assert args == {"action": "read", "path": "x.txt"}

    def test_assistant_turn_openai_no_tools(self, runner):
        """无 tool_use 时, message 只有 content."""
        msg = runner._build_assistant_turn(
            [{"type": "text", "text": "hi"}], ""
        )
        assert msg["content"] == "hi"
        assert "tool_calls" not in msg

    def test_tool_result_openai_shape(self, runner):
        """tool_result 用 OpenAI role=tool + tool_call_id 形态."""
        from jarvis.core.tool_parser import ToolCall
        tc = ToolCall(
            tool="bash", action="execute",
            params={"command": "ls"}, id="call_abc",
        )
        messages: list[dict] = []
        runner._append_tool_result(
            messages, tc, {"status": "success", "stdout": "x"}
        )
        assert len(messages) == 1
        msg = messages[0]
        assert msg["role"] == "tool"
        assert msg["tool_call_id"] == "call_abc"
        assert "[工具结果]" in msg["content"]


# ── OpenAI chat_stream_full SSE 解析 ──────────────────────────────────


class TestOpenAIChatStreamFullParsing:
    """PR3 关键: OpenAI SSE delta.tool_calls 跨 chunk 拼接.

    用 mock httpx.AsyncClient.stream() 喂入真实形态的 SSE bytes,
    验证 chat_stream_full 输出的事件序列.
    """

    @pytest.mark.asyncio
    async def test_stream_with_tool_calls(self):
        a = OpenAIAdapter(model="gpt-4o-mini", api_key="dummy")

        # 喂入的 SSE 模拟 (OpenAI 真实形态)
        sse_lines = [
            'data: {"choices":[{"delta":{"role":"assistant","content":""},"index":0}]}',
            'data: {"choices":[{"delta":{"content":"让我"},"index":0}]}',
            'data: {"choices":[{"delta":{"content":"读文件"},"index":0}]}',
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_abc","type":"function","function":{"name":"file","arguments":""}}]},"index":0}]}',
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\\"action\\":"}}]},"index":0}]}',
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"\\"read\\",\\"path\\":\\"x.txt\\"}"}}]},"index":0}]}',
            'data: {"choices":[{"delta":{},"finish_reason":"tool_calls","index":0}]}',
            "data: [DONE]",
        ]
        sse_body = "\n".join(sse_lines) + "\n"

        # mock httpx response
        mock_resp = MagicMock()
        mock_resp.status_code = 200

        async def aiter_lines():
            for line in sse_body.split("\n"):
                yield line

        mock_resp.aiter_lines = aiter_lines
        mock_resp.raise_for_status = MagicMock()

        # mock stream context manager
        # 用 AsyncMock 模拟 client.stream() 返回的上下文管理器
        stream_cm = MagicMock()
        stream_cm.__aenter__ = AsyncMock(return_value=mock_resp)
        stream_cm.__aexit__ = AsyncMock(return_value=None)

        # client 是 property, 直接设 _client
        fake_client = MagicMock()
        fake_client.stream = MagicMock(return_value=stream_cm)
        a._client = fake_client

        events = []
        async for ev in a.chat_stream_full([{"role": "user", "content": "hi"}]):
            events.append(ev)

        # 1) 应有 text_start → text(text_chunk x N) → text_end
        types = [e["type"] for e in events]
        assert "text_start" in types
        assert "text_end" in types
        text_chunks = [e["content"] for e in events if e["type"] == "text"]
        assert "".join(text_chunks) == "让我读文件"

        # 2) 应有 tool_use_start → tool_use_delta x N → tool_use_end (input 完整)
        assert "tool_use_start" in types
        assert "tool_use_end" in types
        tool_end = next(e for e in events if e["type"] == "tool_use_end")
        assert tool_end["name"] == "file"
        assert tool_end["id"] == "call_abc"
        assert tool_end["input"] == {"action": "read", "path": "x.txt"}

        # 3) 应有 message_delta + message_stop
        assert "message_delta" in types
        assert "message_stop" in types

    @pytest.mark.asyncio
    async def test_stream_text_only(self):
        """无 tool_call 时, 流仅含 text 事件."""
        a = OpenAIAdapter(model="gpt-4o-mini", api_key="dummy")

        sse_lines = [
            'data: {"choices":[{"delta":{"role":"assistant","content":""},"index":0}]}',
            'data: {"choices":[{"delta":{"content":"hi"},"index":0}]}',
            'data: {"choices":[{"delta":{},"finish_reason":"stop","index":0}]}',
            "data: [DONE]",
        ]
        sse_body = "\n".join(sse_lines) + "\n"

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        async def aiter_lines():
            for line in sse_body.split("\n"):
                yield line

        mock_resp.aiter_lines = aiter_lines
        mock_resp.raise_for_status = MagicMock()

        stream_cm = MagicMock()
        stream_cm.__aenter__ = AsyncMock(return_value=mock_resp)
        stream_cm.__aexit__ = AsyncMock(return_value=None)
        fake_client = MagicMock()
        fake_client.stream = MagicMock(return_value=stream_cm)
        a._client = fake_client

        events = []
        async for ev in a.chat_stream_full([{"role": "user", "content": "x"}]):
            events.append(ev)

        types = [e["type"] for e in events]
        assert "tool_use_start" not in types
        assert "text" in types
        assert "message_stop" in types





class TestAgentLoopAnthropicProtocol:
    """PR3 回归: provider_protocol=anthropic (默认) 时, 行为不变."""

    @pytest.fixture
    def runner(self):
        from jarvis.core.agent_loop import AgentLoopRunner, AgentLoopConfig
        return AgentLoopRunner(
            config=AgentLoopConfig(
                max_iterations=4,
                provider_protocol="anthropic",
            ),
            task_executor=MagicMock(),
            tool_parser=MagicMock(),
        )

    def test_assistant_turn_anthropic_shape(self, runner):
        blocks = [
            {"type": "text", "text": ""},
            {"type": "tool_use", "id": "toolu_1", "name": "bash",
             "input": {"command": "ls"}},
        ]
        msg = runner._build_assistant_turn(blocks, "")
        assert msg["role"] == "assistant"
        assert isinstance(msg["content"], list)
        types = [b.get("type") for b in msg["content"]]
        assert "tool_use" in types

    def test_tool_result_anthropic_shape(self, runner):
        from jarvis.core.tool_parser import ToolCall
        tc = ToolCall(tool="bash", action="execute",
                      params={"command": "ls"}, id="toolu_1")
        messages: list[dict] = []
        runner._append_tool_result(
            messages, tc, {"status": "success", "stdout": "x"}
        )
        assert len(messages) == 1
        msg = messages[0]
        assert msg["role"] == "user"
        assert isinstance(msg["content"], list)
        assert msg["content"][0]["type"] == "tool_result"
        assert msg["content"][0]["tool_use_id"] == "toolu_1"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
