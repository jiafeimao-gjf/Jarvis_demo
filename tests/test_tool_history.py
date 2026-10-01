# tests/test_tool_history.py
"""ToolHistoryCompactor 测试 — 验证 tool/tool_result → 自然语言摘要 + 阈值聚合."""
import json
import pytest

from jarvis.core.tool_history import ToolHistoryCompactor, ToolHistoryStats


# ── helpers ─────────────────────────────────────────────────────────

def _tool_call_msg(tool: str, action: str, params: dict, **extra) -> dict:
    """构造一个 tool 调用消息 (与 chat_engine 写入 conversation 时的格式一致)."""
    payload = {"tool": tool, "action": action, "params": params}
    payload.update(extra)
    return {"role": "tool", "content": json.dumps(payload, ensure_ascii=False)}


def _tool_result_msg(text: str) -> dict:
    return {"role": "tool_result", "content": text}


# ── 基础转换 ─────────────────────────────────────────────────────────

class TestTransform:
    def test_empty_history(self):
        c = ToolHistoryCompactor()
        out, stats = c.compact([])
        assert out == []
        assert stats.tool_turns == 0
        assert stats.aggregated is False

    def test_no_tool_messages_passes_through(self):
        c = ToolHistoryCompactor()
        history = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        out, stats = c.compact(history)
        assert out == history
        assert stats.tool_turns == 0

    def test_disabled_compactor_is_noop(self):
        c = ToolHistoryCompactor(enabled=False)
        history = [
            _tool_call_msg("bash", "exec", {"cmd": "ls"}),
            _tool_result_msg("a.txt\nb.txt"),
            {"role": "assistant", "content": "ok"},
        ]
        out, stats = c.compact(history)
        # enabled=False 时, tool/tool_result 保持原样, 由下游 sanitize 处理
        assert out == history
        assert stats.tool_turns == 0

    def test_single_tool_turn_becomes_user_role_summary(self):
        c = ToolHistoryCompactor()
        history = [
            {"role": "user", "content": "list files"},
            _tool_call_msg("bash", "exec", {"cmd": "ls"}),
            _tool_result_msg("a.txt\nb.txt\nc.txt"),
            {"role": "assistant", "content": "There are 3 files."},
        ]
        out, stats = c.compact(history)
        assert stats.tool_turns == 1
        # 顺序: user → 工具摘要 → assistant
        assert [m["role"] for m in out] == ["user", "user", "assistant"]
        summary = out[1]["content"]
        assert "[工具执行]" in summary
        assert "bash.exec" in summary
        assert "ls" in summary
        assert "a.txt" in summary

    def test_skipped_tool_call_marks_status(self):
        c = ToolHistoryCompactor()
        history = [
            _tool_call_msg("bash", "exec", {"cmd": "ls"}, skipped=True, reason="dup"),
            _tool_result_msg("ignored"),
        ]
        out, stats = c.compact(history)
        assert stats.tool_turns == 1
        assert "已跳过" in out[0]["content"]
        assert "dup" in out[0]["content"]

    def test_long_result_is_truncated(self):
        c = ToolHistoryCompactor(max_single_result_chars=50)
        long_text = "x" * 5000
        history = [
            _tool_call_msg("file", "read", {"path": "/tmp/big.txt"}),
            _tool_result_msg(long_text),
        ]
        out, stats = c.compact(history)
        summary = out[0]["content"]
        assert "截断" in summary
        # 摘要本身不能超过 50 + 一堆前缀, 所以肯定 < 5000
        assert len(summary) < 1000

    def test_lone_tool_result_without_call(self):
        """孤立 tool_result (没有对应 tool call) 也能被吸收."""
        c = ToolHistoryCompactor()
        history = [
            {"role": "user", "content": "hi"},
            _tool_result_msg("orphan result"),
            {"role": "assistant", "content": "ok"},
        ]
        out, stats = c.compact(history)
        assert stats.tool_turns == 1
        assert "orphan result" in out[1]["content"]

    def test_consecutive_tool_turns_emit_multiple_summaries(self):
        c = ToolHistoryCompactor()
        history = [
            {"role": "user", "content": "do two things"},
            _tool_call_msg("bash", "exec", {"cmd": "ls"}),
            _tool_result_msg("file1"),
            _tool_call_msg("file", "read", {"path": "file1"}),
            _tool_result_msg("contents"),
            {"role": "assistant", "content": "done"},
        ]
        out, stats = c.compact(history)
        assert stats.tool_turns == 2
        # 顺序: user, summary#1, summary#2, assistant
        assert [m["role"] for m in out] == ["user", "user", "user", "assistant"]
        assert "bash.exec" in out[1]["content"]
        assert "file.read" in out[2]["content"]

    def test_unparseable_tool_content_falls_back_gracefully(self):
        """tool msg content 不是合法 JSON 也不应抛异常."""
        c = ToolHistoryCompactor()
        history = [
            {"role": "user", "content": "hi"},
            {"role": "tool", "content": "this is not JSON {{{"},
            _tool_result_msg("result text"),
            {"role": "assistant", "content": "ok"},
        ]
        out, stats = c.compact(history)
        assert stats.tool_turns == 1
        assert "unknown" in out[1]["content"]
        assert "result text" in out[1]["content"]


# ── 阈值聚合 ─────────────────────────────────────────────────────────

class TestAggregation:
    def _make_long_history(self, num_tool_turns: int) -> list[dict]:
        """构造 N 个工具 turn + 用户/助手对, 每个 tool_result 100 字符."""
        history = []
        for i in range(num_tool_turns):
            history.append({"role": "user", "content": f"q{i}"})
            history.append(
                _tool_call_msg("bash", "exec", {"cmd": f"echo round-{i}"})
            )
            history.append(_tool_result_msg(f"result for round {i}: " + "x" * 80))
            history.append({"role": "assistant", "content": f"a{i}"})
        return history

    def test_no_aggregation_when_under_threshold(self):
        # 2 个 turn, 默认 keep_recent=4, 总 token 不会超 1500
        c = ToolHistoryCompactor(
            aggregate_token_threshold=10000,  # 抬到很高
            keep_recent_turns=2,
        )
        history = self._make_long_history(2)
        out, stats = c.compact(history)
        assert stats.tool_turns == 2
        assert stats.aggregated is False

    def test_aggregation_triggers_when_over_threshold(self):
        # 8 个 turn, threshold 很低, 必然触发
        c = ToolHistoryCompactor(
            aggregate_token_threshold=200,
            keep_recent_turns=2,
        )
        history = self._make_long_history(8)
        out, stats = c.compact(history)
        assert stats.tool_turns == 8  # 转换数 (聚合前的总 turn 数)
        assert stats.aggregated is True
        assert stats.aggregated_count == 6  # 8 - keep_recent(2)
        assert stats.kept_recent == 2

    def test_aggregation_keeps_recent_turns_verbatim(self):
        c = ToolHistoryCompactor(
            aggregate_token_threshold=100,
            keep_recent_turns=2,
        )
        history = self._make_long_history(5)
        out, stats = c.compact(history)
        assert stats.aggregated is True
        # 找包含 "工具执行" (不是"早期工具执行摘要") 的消息
        singles = [m for m in out if "[工具执行]" in m["content"]]
        # 应保留最近 2 个
        assert len(singles) == 2
        # 最近两个是 round-3 和 round-4
        assert "round-3" in singles[-2]["content"] or "round-4" in singles[-1]["content"]

    def test_aggregation_creates_aggregate_marker(self):
        c = ToolHistoryCompactor(
            aggregate_token_threshold=100,
            keep_recent_turns=1,
        )
        history = self._make_long_history(4)
        out, stats = c.compact(history)
        aggregate = [m for m in out if "[早期工具执行摘要]" in m["content"]]
        assert len(aggregate) == 1
        assert "共 3 次工具调用" in aggregate[0]["content"]

    def test_aggregation_reduces_token_count(self):
        c = ToolHistoryCompactor(
            aggregate_token_threshold=100,
            keep_recent_turns=2,
        )
        history = self._make_long_history(8)
        out, stats = c.compact(history)
        assert stats.total_before_tokens > stats.total_after_tokens

    def test_no_aggregation_when_too_few_turns(self):
        """turn 数 <= keep_recent 时, 不聚合 (无可聚合)."""
        c = ToolHistoryCompactor(
            aggregate_token_threshold=10,  # 阈值极低
            keep_recent_turns=5,
        )
        history = self._make_long_history(3)
        out, stats = c.compact(history)
        # 3 turns, keep_recent=5, len <= keep → no aggregation
        assert stats.aggregated is False
        # 每个 turn 仍是单独摘要
        assert stats.tool_turns == 3


# ── 集成: 与 ContextManager 配合 ──────────────────────────────────────

class TestIntegration:
    @pytest.mark.asyncio
    async def test_context_manager_runs_tool_history_compactor(self):
        from jarvis.core.context_manager import ContextManager
        cm = ContextManager()
        history = [
            {"role": "user", "content": "list files"},
            _tool_call_msg("bash", "exec", {"cmd": "ls"}),
            _tool_result_msg("a.txt\nb.txt"),
            {"role": "assistant", "content": "found 2 files"},
            {"role": "user", "content": "now read a.txt"},
        ]
        result = await cm.build_messages(
            system_prompt="S.",
            history=history,
            current_user_input="next",
        )
        msgs = result["messages"]
        # 工具摘要应在 user 消息之后, assistant 之前
        # 找到所有 role=user 的消息, 应该含 [工具执行]
        user_msgs = [m for m in msgs if m["role"] == "user"]
        assert any("[工具执行]" in m["content"] for m in user_msgs)
        # 不应再有 role=tool 的消息 (被 _sanitize_history 兜底丢)
        assert not any(m["role"] in ("tool", "tool_result") for m in msgs)
        # stats 包含 tool_history
        assert "tool_history" in result["stats"]
        assert result["stats"]["tool_history"]["tool_turns"] == 1

    @pytest.mark.asyncio
    async def test_custom_compactor_params(self):
        from jarvis.core.context_manager import ContextManager
        compactor = ToolHistoryCompactor(
            aggregate_token_threshold=50,
            keep_recent_turns=1,
            max_single_result_chars=20,
        )
        cm = ContextManager(tool_history_compactor=compactor)
        # 构造 3 个 turn, 触发聚合
        history = []
        for i in range(3):
            history.append({"role": "user", "content": f"q{i}"})
            history.append(
                _tool_call_msg("bash", "exec", {"cmd": f"echo {i}"})
            )
            history.append(_tool_result_msg("y" * 100))
            history.append({"role": "assistant", "content": f"a{i}"})
        result = await cm.build_messages(
            system_prompt="S.",
            history=history,
            current_user_input="next",
        )
        stats = result["stats"]["tool_history"]
        assert stats["tool_turns"] == 3
        assert stats["aggregated"] is True
        assert stats["aggregated_count"] == 2

    @pytest.mark.asyncio
    async def test_disabled_compactor_drops_tool_messages(self):
        """ToolHistoryCompactor disabled → tool msgs 走到 _sanitize_history 被丢."""
        from jarvis.core.context_manager import ContextManager
        compactor = ToolHistoryCompactor(enabled=False)
        cm = ContextManager(tool_history_compactor=compactor)
        history = [
            {"role": "user", "content": "hi"},
            _tool_call_msg("bash", "exec", {"cmd": "ls"}),
            _tool_result_msg("files"),
            {"role": "assistant", "content": "ok"},
        ]
        result = await cm.build_messages(
            system_prompt="S.",
            history=history,
            current_user_input="next",
        )
        msgs = result["messages"]
        # 不应含 tool/tool_result
        assert not any(m["role"] in ("tool", "tool_result") for m in msgs)
        # stats 应记录 tool_turns=0 (因为 compactor 没跑)
        assert result["stats"]["tool_history"]["tool_turns"] == 0
