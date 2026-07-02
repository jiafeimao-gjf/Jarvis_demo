# tests/test_context_compressor.py
"""ContextCompressor 模块测试 — 阈值触发、LLM 摘要、冷却、持久化、与 ContextManager 集成."""
import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock

from jarvis.core.context_compressor import (
    AdaptiveTrigger,
    CompressedContext,
    ContextCompressor,
    ContextUsage,
    ThresholdTrigger,
    default_summarize,
)
from jarvis.core.context_manager import ContextManager
from jarvis.core.entities import Conversation, Message


# ── Helpers ────────────────────────────────────────────────────────

def make_conversation(messages_data: list[tuple[str, str]], conv_id: str = "test-conv") -> Conversation:
    """[(role, content), ...] -> Conversation"""
    conv = Conversation(conversation_id=conv_id)
    for role, content in messages_data:
        conv.add_message(role, content)
    return conv


def make_router(summary: str = "压缩后的摘要") -> MagicMock:
    router = MagicMock()
    router.chat = AsyncMock(return_value=MagicMock(content=summary))
    return router


# ── ThresholdTrigger ───────────────────────────────────────────────

class TestThresholdTrigger:
    def test_below_threshold_does_not_trigger(self):
        t = ThresholdTrigger(threshold=0.75)
        usage = ContextUsage(
            total_tokens=500, budget_tokens=1000,
            threshold_tokens=750, message_count=10,
        )
        assert t.should_compress(usage) is False

    def test_at_threshold_triggers(self):
        t = ThresholdTrigger(threshold=0.75)
        usage = ContextUsage(
            total_tokens=750, budget_tokens=1000,
            threshold_tokens=750, message_count=10,
        )
        assert t.should_compress(usage) is True

    def test_above_threshold_triggers(self):
        t = ThresholdTrigger(threshold=0.75)
        usage = ContextUsage(
            total_tokens=900, budget_tokens=1000,
            threshold_tokens=750, message_count=20,
        )
        assert t.should_compress(usage) is True

    def test_invalid_threshold_rejected(self):
        with pytest.raises(ValueError):
            ThresholdTrigger(threshold=1.5)
        with pytest.raises(ValueError):
            ThresholdTrigger(threshold=0)

    def test_describe(self):
        assert "0.75" in ThresholdTrigger(threshold=0.75).describe()


# ── AdaptiveTrigger ────────────────────────────────────────────────

class TestAdaptiveTrigger:
    def test_threshold_path(self):
        t = AdaptiveTrigger(threshold=0.75)
        usage = ContextUsage(
            total_tokens=900, budget_tokens=1000,
            threshold_tokens=750, message_count=20,
        )
        assert t.should_compress(usage) is True

    def test_growth_path_triggers(self):
        t = AdaptiveTrigger(threshold=0.75, growth_threshold_tokens=1500)
        # 低于阈值, 但增长过快
        usage = ContextUsage(
            total_tokens=500, budget_tokens=1000,
            threshold_tokens=750, message_count=5,
        )
        usage._conv_id = "conv1"  # 注入 conv_id
        assert t.should_compress(usage) is False  # 第一次没历史, 不触发
        t.update_last_tokens("conv1", 0)  # 模拟上次 0 tokens
        # 现在增长 500, 还没到 1500, 不触发
        assert t.should_compress(usage) is False
        t.update_last_tokens("conv1", 100)
        usage2 = ContextUsage(
            total_tokens=2000, budget_tokens=5000,
            threshold_tokens=3750, message_count=10,
        )
        usage2._conv_id = "conv1"
        # 增长 1900 > 1500, 触发
        assert t.should_compress(usage2) is True

    def test_describe(self):
        d = AdaptiveTrigger(threshold=0.7, growth_threshold_tokens=1000).describe()
        assert "0.7" in d
        assert "1000" in d


# ── ContextUsage ───────────────────────────────────────────────────

class TestContextUsage:
    def test_ratio(self):
        u = ContextUsage(total_tokens=500, budget_tokens=1000,
                         threshold_tokens=750, message_count=10)
        assert u.ratio == 0.5

    def test_ratio_floor(self):
        u = ContextUsage(total_tokens=0, budget_tokens=0,
                         threshold_tokens=0, message_count=0)
        assert u.ratio == 0.0  # max(0, 1) -> 1, 0/1 = 0

    def test_over_threshold(self):
        u1 = ContextUsage(total_tokens=749, budget_tokens=1000,
                          threshold_tokens=750, message_count=10)
        u2 = ContextUsage(total_tokens=750, budget_tokens=1000,
                          threshold_tokens=750, message_count=10)
        assert u1.over_threshold is False
        assert u2.over_threshold is True

    def test_to_dict(self):
        u = ContextUsage(total_tokens=500, budget_tokens=1000,
                         threshold_tokens=750, message_count=10)
        d = u.to_dict()
        assert d["ratio"] == 0.5
        assert d["over_threshold"] is False


# ── default_summarize ──────────────────────────────────────────────

class TestDefaultSummarize:
    @pytest.mark.asyncio
    async def test_calls_router_chat(self):
        router = make_router("这是摘要")
        result = await default_summarize(
            router,
            [{"role": "user", "content": "hi"},
             {"role": "assistant", "content": "hello"}],
            model="qwen3:4b",
        )
        assert result == "这是摘要"
        router.chat.assert_called_once()
        # 检查消息构造 (kwargs 形式调用)
        call_kwargs = router.chat.call_args.kwargs
        msgs = call_kwargs["messages"]
        assert msgs[0]["role"] == "system"
        assert "压缩员" in msgs[0]["content"]
        assert "[user]" in msgs[1]["content"]
        assert "[assistant]" in msgs[1]["content"]
        assert call_kwargs["model"] == "qwen3:4b"
        assert call_kwargs["stream"] is False

    @pytest.mark.asyncio
    async def test_handles_anthropic_blocks(self):
        router = make_router("ok")
        msgs = [
            {"role": "assistant", "content": [
                {"type": "text", "text": "hi"},
                {"type": "tool_use", "name": "x", "input": {}},
            ]},
        ]
        await default_summarize(router, msgs)
        call_kwargs = router.chat.call_args.kwargs
        prompt = call_kwargs["messages"][1]["content"]
        assert "[assistant] hi" in prompt  # 只取 text 块, 加上 role 标记
        assert "tool_use" not in prompt  # 不包含 tool_use 块

    @pytest.mark.asyncio
    async def test_returns_empty_on_router_failure(self):
        router = MagicMock()
        router.chat = AsyncMock(side_effect=RuntimeError("LLM down"))
        result = await default_summarize(router, [{"role": "user", "content": "x"}])
        assert result == ""


# ── ContextCompressor.measure ──────────────────────────────────────

class TestMeasure:
    def test_measure_empty(self):
        c = ContextCompressor(router=make_router())
        conv = make_conversation([])
        usage = c.measure(conv)
        assert usage.total_tokens == 0
        assert usage.message_count == 0
        assert usage.budget_tokens > 0  # 默认模型有 context_window

    def test_measure_populated(self):
        c = ContextCompressor(router=make_router())
        conv = make_conversation([
            ("user", "hello"),
            ("assistant", "hi there"),
        ])
        usage = c.measure(conv)
        assert usage.total_tokens > 0
        assert usage.message_count == 2

    def test_measure_uses_model_context_window(self):
        c = ContextCompressor(router=make_router())
        conv = make_conversation([("user", "hi")])
        # gpt-4o 已知 context_window=128000
        usage = c.measure(conv, model_id="gpt-4o")
        assert usage.budget_tokens == 128000


# ── ContextCompressor.should_compress ──────────────────────────────

class TestShouldCompress:
    def test_too_few_messages(self):
        c = ContextCompressor(router=make_router(), min_messages=6)
        conv = make_conversation([("user", "hi")] * 3)
        assert c.should_compress(conv) is False

    def test_below_threshold(self):
        c = ContextCompressor(
            router=make_router(),
            trigger=ThresholdTrigger(0.99),
        )
        conv = make_conversation([("user", "hi")] * 20)
        # 20 条短消息远不到 99% 阈值
        assert c.should_compress(conv) is False

    def test_above_threshold(self):
        c = ContextCompressor(
            router=make_router(),
            trigger=ThresholdTrigger(0.01),  # 极低阈值, 任何东西都触发
            min_messages=2,
        )
        conv = make_conversation([("user", "x" * 1000)] * 50)
        assert c.should_compress(conv) is True


# ── ContextCompressor.maybe_compress ───────────────────────────────

class TestMaybeCompress:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_trigger(self):
        c = ContextCompressor(
            router=make_router(),
            trigger=ThresholdTrigger(0.99),  # 几乎不触发
        )
        conv = make_conversation([("user", "hi")] * 5)
        result = await c.maybe_compress(conv)
        assert result is None

    @pytest.mark.asyncio
    async def test_force_bypasses_all_checks(self):
        c = ContextCompressor(
            router=make_router("forced summary"),
            trigger=ThresholdTrigger(0.99),
            min_messages=999,  # 正常情况下不会触发
        )
        conv = make_conversation([("user", "hi"), ("assistant", "hello")])
        result = await c.maybe_compress(conv, force=True)
        assert result is not None
        assert result.summary == "forced summary"

    @pytest.mark.asyncio
    async def test_replaces_messages_with_summary(self):
        c = ContextCompressor(
            router=make_router("这是压缩摘要"),
            keep_recent=2,
            min_messages=2,
            trigger=ThresholdTrigger(0.01),
        )
        # 5 条消息, 留尾部 2 条原文, 前 3 条被摘要
        conv = make_conversation([
            ("user", "u1"), ("assistant", "a1"),
            ("user", "u2"), ("assistant", "a2"),
            ("user", "u3"),
        ])
        result = await c.maybe_compress(conv, force=True)
        assert result is not None
        assert result.dropped_count == 3
        # 替换后: 1 条 summary + 2 条原文 = 3 条
        assert len(conv.messages) == 3
        assert conv.messages[0].role == "system"
        assert "压缩摘要" in conv.messages[0].content
        assert conv.messages[-1].content == "u3"  # 最近一条保留

    @pytest.mark.asyncio
    async def test_empty_summarizer_does_not_modify(self):
        c = ContextCompressor(
            router=make_router(""),  # 摘要返回空
            keep_recent=2,
            min_messages=2,
            trigger=ThresholdTrigger(0.01),
        )
        conv = make_conversation([("user", "x")] * 5)
        original_len = len(conv.messages)
        result = await c.maybe_compress(conv, force=True)
        assert result is None
        assert len(conv.messages) == original_len  # 未修改

    @pytest.mark.asyncio
    async def test_persist_fn_called(self):
        persist_fn = AsyncMock()
        c = ContextCompressor(
            router=make_router("sum"),
            keep_recent=2,
            min_messages=2,
            trigger=ThresholdTrigger(0.01),
            persist_fn=persist_fn,
        )
        conv = make_conversation([("user", "x")] * 5)
        await c.maybe_compress(conv, force=True)
        persist_fn.assert_called_once_with(conv)

    @pytest.mark.asyncio
    async def test_persist_failure_does_not_break(self):
        async def bad_persist(conv):
            raise RuntimeError("db down")
        c = ContextCompressor(
            router=make_router("sum"),
            min_messages=2,
            trigger=ThresholdTrigger(0.01),
            persist_fn=bad_persist,
        )
        conv = make_conversation([("user", "x")] * 5)
        # 不应抛异常
        result = await c.maybe_compress(conv, force=True)
        assert result is not None


# ── 冷却机制 ──────────────────────────────────────────────────────

class TestCooldown:
    @pytest.mark.asyncio
    async def test_cooldown_blocks_repeat(self):
        c = ContextCompressor(
            router=make_router("sum"),
            min_messages=2,
            cooldown_seconds=10.0,
            trigger=ThresholdTrigger(0.5),  # 50% 阈值, 长消息能触发
        )
        # 用 5000 字符的消息, 5 条 ≈ 6000+ tokens, 远超 50% of 8192
        conv = make_conversation([("user", "x" * 5000)] * 5)
        r1 = await c.maybe_compress(conv)
        assert r1 is not None
        # 第二次: 冷却中 (cooldown=10s)
        r2 = await c.maybe_compress(conv)
        assert r2 is None

    @pytest.mark.asyncio
    async def test_cooldown_expires(self):
        c = ContextCompressor(
            router=make_router("sum"),
            min_messages=2,
            cooldown_seconds=0.05,
            trigger=ThresholdTrigger(0.5),
        )
        conv = make_conversation([("user", "x" * 5000)] * 5)
        r1 = await c.maybe_compress(conv)
        assert r1 is not None
        await asyncio.sleep(0.1)
        # 添加新消息让消息数重新满足 min_messages
        conv.add_message("user", "x" * 5000)
        conv.add_message("assistant", "x" * 5000)
        r2 = await c.maybe_compress(conv)
        # 冷却已过, 会再次压缩
        assert r2 is not None


# ── 统计 ───────────────────────────────────────────────────────────

class TestStats:
    @pytest.mark.asyncio
    async def test_compress_count_increments(self):
        c = ContextCompressor(
            router=make_router("sum"),
            min_messages=2,
            cooldown_seconds=0.0,
            trigger=ThresholdTrigger(0.5),
        )
        # 长消息确保超过阈值
        conv1 = make_conversation([("user", "x" * 5000)] * 5, conv_id="c1")
        await c.maybe_compress(conv1)
        assert c.get_stats("c1")["compress_count"] == 1

    def test_reset_stats(self):
        c = ContextCompressor(router=make_router())
        c._compress_count["c1"] = 3
        c._last_compress_at["c1"] = time.time()
        c.reset_stats("c1")
        assert c.get_stats("c1")["compress_count"] == 0

    def test_reset_all(self):
        c = ContextCompressor(router=make_router())
        c._compress_count["c1"] = 3
        c._compress_count["c2"] = 5
        c.reset_stats()
        assert c._compress_count == {}


# ── 与 ContextManager 集成 ─────────────────────────────────────────

class TestIntegrationWithContextManager:
    @pytest.mark.asyncio
    async def test_compressor_triggers_via_build_messages(self):
        """ContextManager 传 compressor + conversation 时, 应触发压缩."""
        from jarvis.core.context_manager import HybridStrategy
        router = make_router("由 compressor 生成的摘要")
        compressor = ContextCompressor(
            router=router,
            trigger=ThresholdTrigger(0.5),  # 50% 阈值, 长消息能触发
            keep_recent=2,
            min_messages=2,
        )
        cm = ContextManager(strategy=HybridStrategy(), compressor=compressor)

        # 用长消息确保超阈值
        conv = make_conversation(
            [(("user" if i % 2 == 0 else "assistant"), "x" * 5000) for i in range(10)]
        )

        result = await cm.build_messages(
            system_prompt="System.",
            history=[{"role": m.role, "content": m.content} for m in conv.messages],
            current_user_input="new",
            model_id=None,
            conversation=conv,
        )
        # compressor 已被调用, history 应被压缩成 1 summary + 2 原文
        assert result["stats"]["compressed"] is True
        assert result["stats"]["history_in"] == 3

    @pytest.mark.asyncio
    async def test_no_compressor_no_compression(self):
        """不传 compressor 时, build_messages 不触发压缩."""
        cm = ContextManager()
        conv = make_conversation([("user", "x")] * 100)
        result = await cm.build_messages(
            system_prompt="S.",
            history=[{"role": m.role, "content": m.content} for m in conv.messages],
            current_user_input="hi",
            conversation=conv,
        )
        # 没有 compressor, 不压缩
        assert result["stats"]["compressed"] is False
        # history_in 应该是原始传入的数量 (经过 stream chat 之前的限制)
        assert result["stats"]["history_in"] == 100

    @pytest.mark.asyncio
    async def test_compressor_error_does_not_break_build(self):
        """compressor 抛异常时, build_messages 应继续工作."""
        compressor = ContextCompressor(
            router=MagicMock(chat=AsyncMock(side_effect=RuntimeError("boom"))),
            trigger=ThresholdTrigger(0.01),
            min_messages=2,
        )
        cm = ContextManager(compressor=compressor)
        conv = make_conversation([("user", "x")] * 10)
        result = await cm.build_messages(
            system_prompt="S.",
            history=[{"role": m.role, "content": m.content} for m in conv.messages],
            current_user_input="hi",
            conversation=conv,
        )
        # 不应抛异常, 返回正常 messages
        assert len(result["messages"]) > 0


# ── CompressedContext ──────────────────────────────────────────────

class TestCompressedContext:
    def test_to_dict_shape(self):
        from datetime import datetime
        ctx = CompressedContext(
            conversation_id="c1",
            summary="sum",
            kept_messages=[],
            dropped_count=10,
            before_tokens=1000,
            after_tokens=200,
            compression_ratio=5.0,
        )
        d = ctx.to_dict()
        assert d["conversation_id"] == "c1"
        assert d["summary_len"] == 3
        assert d["dropped_count"] == 10
        assert d["before_tokens"] == 1000
        assert d["after_tokens"] == 200
        assert d["compression_ratio"] == 5.0
        assert d["trigger_reason"] == "threshold"
        assert "triggered_at" in d