# tests/test_context_manager.py
"""ContextManager 模块测试 — token 预算、压缩策略、记忆注入."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from jarvis.core.context_manager import (
    ContextBudget,
    ContextManager,
    SlidingWindowStrategy,
    SummarizationStrategy,
    HybridStrategy,
    CompactionResult,
    count_tokens,
    messages_tokens,
)


# ── Token counting ─────────────────────────────────────────────────

class TestTokenCounting:
    def test_count_tokens_empty(self):
        assert count_tokens("") == 0
        assert count_tokens(None) == 0

    def test_count_tokens_chinese(self):
        # 中文字符大概 1.5-2 字节/token, 这里只测 > 0
        n = count_tokens("你好世界")
        assert n > 0

    def test_count_tokens_english(self):
        n = count_tokens("hello world this is a test")
        assert n > 0

    def test_messages_tokens_basic(self):
        msgs = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello!"},
        ]
        n = messages_tokens(msgs)
        assert n > 4  # 至少包含 4 token 角色开销

    def test_messages_tokens_anthropic_blocks(self):
        msgs = [
            {"role": "assistant", "content": [
                {"type": "text", "text": "hello"},
                {"type": "tool_use", "name": "file", "input": {"action": "read"}},
            ]},
        ]
        n = messages_tokens(msgs)
        assert n > 0


# ── SlidingWindowStrategy ──────────────────────────────────────────

class TestSlidingWindow:
    @pytest.mark.asyncio
    async def test_returns_last_n(self):
        s = SlidingWindowStrategy(max_recent=3)
        history = [{"role": "user", "content": f"msg{i}"} for i in range(10)]
        result = await s.compact(history, ContextBudget(max_context_window=100000))
        assert len(result.messages) == 3
        assert result.messages[-1]["content"] == "msg9"
        assert result.dropped_count == 7
        assert result.summary_added is False

    @pytest.mark.asyncio
    async def test_respects_token_budget(self):
        # 1000 char messages, budget very tight
        history = [
            {"role": "user", "content": "x" * 1000}
            for _ in range(10)
        ]
        budget = ContextBudget(
            max_context_window=500,
            reserve_for_output=200,
            reserve_for_memory=0,
            reserve_for_system=0,
            min_keep_recent=2,
        )
        result = await SlidingWindowStrategy(max_recent=20).compact(history, budget)
        # must keep at least min_keep_recent=2 and trim from front
        assert len(result.messages) >= budget.min_keep_recent
        assert result.dropped_count >= 8

    @pytest.mark.asyncio
    async def test_short_history_not_dropped(self):
        s = SlidingWindowStrategy(max_recent=10)
        history = [{"role": "user", "content": "only msg"}]
        result = await s.compact(history, ContextBudget(max_context_window=100000))
        assert len(result.messages) == 1
        assert result.dropped_count == 0


# ── SummarizationStrategy ──────────────────────────────────────────

class TestSummarization:
    @pytest.mark.asyncio
    async def test_no_compression_when_under_budget(self):
        s = SummarizationStrategy()
        history = [{"role": "user", "content": "short"}]
        budget = ContextBudget(max_context_window=100000)
        result = await s.compact(history, budget)
        assert result.summary_added is False
        assert result.dropped_count == 0

    @pytest.mark.asyncio
    async def test_falls_back_to_window_when_no_summarizer(self):
        s = SummarizationStrategy()
        history = [{"role": "user", "content": "x" * 5000}] * 20
        budget = ContextBudget(
            max_context_window=2000,
            reserve_for_output=500,
            reserve_for_memory=0,
            min_keep_recent=2,
        )
        result = await s.compact(history, budget, summarizer=None)
        # No summarizer → drop older messages, keep at least min_keep_recent
        assert result.summary_added is False
        assert len(result.messages) >= budget.min_keep_recent

    @pytest.mark.asyncio
    async def test_calls_summarizer_when_over_budget(self):
        s = SummarizationStrategy()
        history = [{"role": "user", "content": "x" * 2000}] * 20
        budget = ContextBudget(
            max_context_window=3000,
            reserve_for_output=500,
            reserve_for_memory=0,
            min_keep_recent=3,
        )

        async def fake_summarizer(msgs):
            return "summary of older messages"

        result = await s.compact(history, budget, summarizer=fake_summarizer)
        assert result.summary_added is True
        assert result.dropped_count > 0
        # First message should be the summary block
        assert "历史对话摘要" in result.messages[0]["content"]
        assert "summary of older messages" in result.messages[0]["content"]
        # Recent messages preserved at the tail
        assert result.messages[-1]["content"] == "x" * 2000

    @pytest.mark.asyncio
    async def test_summarizer_exception_falls_back(self):
        s = SummarizationStrategy()
        history = [{"role": "user", "content": "x" * 2000}] * 20
        budget = ContextBudget(
            max_context_window=3000, reserve_for_output=500,
            min_keep_recent=3,
        )

        async def bad_summarizer(msgs):
            raise RuntimeError("LLM down")

        result = await s.compact(history, budget, summarizer=bad_summarizer)
        assert result.summary_added is False
        assert len(result.messages) >= budget.min_keep_recent


# ── ContextManager.build_messages ──────────────────────────────────

class TestBuildMessages:
    @pytest.mark.asyncio
    async def test_basic(self):
        cm = ContextManager()
        history = [{"role": "user", "content": "old"}, {"role": "assistant", "content": "old-reply"}]
        result = await cm.build_messages(
            system_prompt="You are helpful.",
            history=history,
            current_user_input="new question",
        )
        msgs = result["messages"]
        assert msgs[0]["role"] == "system"
        assert "You are helpful." in msgs[0]["content"]
        # Last message must be the current user input
        assert msgs[-1]["role"] == "user"
        assert msgs[-1]["content"] == "new question"
        # History preserved
        assert any(m["content"] == "old" for m in msgs)

    @pytest.mark.asyncio
    async def test_injects_memory(self):
        cm = ContextManager()

        async def fake_retrieve(query, top_k):
            return [{"content": f"relevant: {query}"}, {"content": "fact: 2+2=4"}]

        result = await cm.build_messages(
            system_prompt="System.",
            history=[],
            current_user_input="what is 2+2?",
            memory_retriever=fake_retrieve,
        )
        sys_msg = result["messages"][0]["content"]
        assert "相关记忆" in sys_msg
        assert "relevant: what is 2+2?" in sys_msg
        assert "fact: 2+2=4" in sys_msg
        assert result["stats"]["memory_chunks"] == 2

    @pytest.mark.asyncio
    async def test_memory_retrieve_failure_is_swallowed(self):
        cm = ContextManager()

        async def broken_retrieve(query, top_k):
            raise RuntimeError("db down")

        result = await cm.build_messages(
            system_prompt="System.",
            history=[],
            current_user_input="hi",
            memory_retriever=broken_retrieve,
        )
        assert result["stats"]["memory_chunks"] == 0
        assert result["messages"][-1]["content"] == "hi"

    @pytest.mark.asyncio
    async def test_no_memory_retriever(self):
        cm = ContextManager()
        result = await cm.build_messages(
            system_prompt="S.",
            history=[],
            current_user_input="hi",
            memory_retriever=None,
        )
        assert result["stats"]["memory_chunks"] == 0

    @pytest.mark.asyncio
    async def test_token_budget_from_modelfile(self):
        # gpt-4o has context_window=128000, very loose budget
        cm = ContextManager()
        result = await cm.build_messages(
            system_prompt="S.",
            history=[{"role": "user", "content": "hi"}],
            current_user_input="next",
            model_id="gpt-4o",
        )
        assert result["stats"]["budget_available"] > 100000

    @pytest.mark.asyncio
    async def test_token_budget_unknown_model_uses_default(self):
        cm = ContextManager()
        result = await cm.build_messages(
            system_prompt="S.",
            history=[],
            current_user_input="hi",
            model_id="unknown-model-xyz",
        )
        # Default budget 8192 minus output/memory reserve
        assert 0 < result["stats"]["budget_available"] <= 8192

    @pytest.mark.asyncio
    async def test_stats_reflect_compaction(self):
        cm = ContextManager()
        history = [{"role": "user", "content": "x" * 5000}] * 50
        result = await cm.build_messages(
            system_prompt="S.",
            history=history,
            current_user_input="hi",
            model_id="qwen3:4b",  # no context_window set, default 8192
        )
        stats = result["stats"]
        assert stats["history_in"] == 50
        assert stats["history_out"] < 50
        assert stats["dropped"] > 0
        assert stats["tokens_estimate"] > 0

    @pytest.mark.asyncio
    async def test_current_user_image_passthrough(self):
        cm = ContextManager()
        result = await cm.build_messages(
            system_prompt="S.",
            history=[],
            current_user_input="what is this?",
            current_user_image="/tmp/x.jpg",
        )
        last = result["messages"][-1]
        assert last["role"] == "user"
        assert last["content"] == "what is this?"
        assert last["image"] == "/tmp/x.jpg"


# ── HybridStrategy ─────────────────────────────────────────────────

class TestHybridStrategy:
    @pytest.mark.asyncio
    async def test_hybrid_delegates_to_summarization(self):
        s = HybridStrategy()
        history = [{"role": "user", "content": "hi"}]
        budget = ContextBudget(max_context_window=100000)
        result = await s.compact(history, budget)
        assert isinstance(result, CompactionResult)
        assert len(result.messages) == 1


# ── ContextBudget ──────────────────────────────────────────────────

class TestContextBudget:
    def test_available_for_history(self):
        b = ContextBudget(
            max_context_window=8192,
            reserve_for_output=1024,
            reserve_for_system=500,
            reserve_for_memory=800,
        )
        # 8192 - 1024 - 500 - 800 = 5868
        assert b.available_for_history == 5868

    def test_floor_at_512(self):
        b = ContextBudget(
            max_context_window=100,
            reserve_for_output=1000,
            reserve_for_memory=1000,
        )
        # Even when negative, floor at 512
        assert b.available_for_history == 512