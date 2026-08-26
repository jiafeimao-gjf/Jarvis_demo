# tests/test_pr4_history_subagent_settings.py
"""PR4 测试:
  - ContextManager._normalize_history 历史回放策略
  - Subagent max_iterations 跟随主对话 (从 BaseSubagent 实例属性读取)
  - ChatEngine._apply_runtime_settings 从 Settings 注入 max_iterations
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from jarvis.core.context_manager import ContextManager


# ── ContextManager._normalize_history (PR4 HistoryReplayPolicy) ──────


class TestNormalizeHistory:
    """PR4: history 回放策略 — 默认 strict, 可选 lenient."""

    def test_strict_drops_tool_role(self):
        """strict 模式下, tool / tool_result 角色被剔除."""
        history = [
            {"role": "user", "content": "hi"},
            {"role": "tool", "content": "[TOOL_RESULT] ok"},
            {"role": "tool_result", "content": "result"},
            {"role": "assistant", "content": "response"},
        ]
        cleaned, dropped = ContextManager._normalize_history(history, policy="strict")
        roles = [m["role"] for m in cleaned]
        assert roles == ["user", "assistant"]
        assert dropped == 2

    def test_strict_drops_empty_content(self):
        """strict 模式下, 空字符串 / None content 被剔除."""
        history = [
            {"role": "user", "content": "hi"},
            {"role": "user", "content": ""},
            {"role": "user", "content": "   "},
            {"role": "assistant", "content": None},
            {"role": "assistant", "content": "ok"},
        ]
        cleaned, dropped = ContextManager._normalize_history(history, policy="strict")
        assert len(cleaned) == 2
        assert dropped == 3

    def test_strict_drops_non_dict(self):
        """strict 模式下, 非 dict 项被剔除."""
        history = [
            {"role": "user", "content": "hi"},
            "not a dict",
            None,
            42,
        ]
        cleaned, dropped = ContextManager._normalize_history(history, policy="strict")
        assert len(cleaned) == 1
        assert dropped == 3

    def test_lenient_keeps_tool_role(self):
        """lenient 模式下, tool role 保留 (content 是 str 时)."""
        history = [
            {"role": "user", "content": "hi"},
            {"role": "tool", "content": "[TOOL_RESULT] ok"},
            {"role": "assistant", "content": "response"},
        ]
        cleaned, dropped = ContextManager._normalize_history(history, policy="lenient")
        roles = [m["role"] for m in cleaned]
        assert "tool" in roles
        assert dropped == 0

    def test_lenient_drops_empty_string_content(self):
        """lenient 模式下, 空字符串 content 仍被剔除."""
        history = [
            {"role": "user", "content": ""},
            {"role": "user", "content": "hi"},
        ]
        cleaned, dropped = ContextManager._normalize_history(history, policy="lenient")
        assert len(cleaned) == 1
        assert dropped == 1

    def test_policy_default_strict(self):
        """不传 policy 时, 默认 strict."""
        history = [
            {"role": "user", "content": "hi"},
            {"role": "tool", "content": "[TOOL_RESULT] ok"},
        ]
        cleaned, dropped = ContextManager._normalize_history(history)
        assert dropped == 1

    def test_sanitize_history_alias(self):
        """_sanitize_history 仍是合法别名 (向后兼容)."""
        history = [
            {"role": "user", "content": "hi"},
            {"role": "tool", "content": "x"},
        ]
        cleaned, dropped = ContextManager._sanitize_history(history)
        assert dropped == 1


# ── Subagent max_iterations 跟随主对话 ──────────────────────────────


class TestSubagentMaxIterations:
    """PR4: BaseSubagent.max_iterations 由构造参数注入, 不再来自 SubagentConfig."""

    def test_default_8_when_none(self):
        from jarvis.core.subagent import create_subagent, SubagentRole
        agent = create_subagent(SubagentRole.RESEARCHER, MagicMock())
        assert agent.max_iterations == 8

    def test_explicit_value(self):
        from jarvis.core.subagent import create_subagent, SubagentRole
        agent = create_subagent(
            SubagentRole.RESEARCHER, MagicMock(), max_iterations=15
        )
        assert agent.max_iterations == 15

    def test_config_no_longer_has_max_iterations(self):
        """SubagentConfig 已删除 max_iterations 字段."""
        from jarvis.core.subagent import SubagentConfig
        config = SubagentConfig(
            role=__import__("jarvis.core.subagent", fromlist=["SubagentRole"]).SubagentRole.RESEARCHER,
            system_prompt="x",
        )
        assert not hasattr(config, "max_iterations")


# ── ChatEngine._apply_runtime_settings ──────────────────────────────


class TestApplyRuntimeSettings:
    """PR4: ChatEngine 从 Settings DB 读 tool_loop_max_iterations, 注入 runner."""

    @pytest.mark.asyncio
    async def test_injects_max_iterations(self):
        from jarvis.core.chat_engine import ChatEngine
        with patch("jarvis.core.chat_engine.memory_store") as mock_store:
            mock_store.get_all_settings = AsyncMock(
                return_value={"tool_loop_max_iterations": 12}
            )
            engine = ChatEngine()
            await engine._apply_runtime_settings()
        assert engine.agent_loop_runner.config.max_iterations == 12
        assert engine.subagent_orchestrator.max_iterations == 12

    @pytest.mark.asyncio
    async def test_clamps_to_1_20(self):
        from jarvis.core.chat_engine import ChatEngine
        for raw, expected in [(0, 1), (5, 5), (25, 20), (100, 20)]:
            with patch("jarvis.core.chat_engine.memory_store") as mock_store:
                mock_store.get_all_settings = AsyncMock(
                    return_value={"tool_loop_max_iterations": raw}
                )
                engine = ChatEngine()
                await engine._apply_runtime_settings()
            assert engine.agent_loop_runner.config.max_iterations == expected, (
                f"raw={raw} → expected={expected}, "
                f"got={engine.agent_loop_runner.config.max_iterations}"
            )

    @pytest.mark.asyncio
    async def test_missing_setting_keeps_default(self):
        """Settings 没设 tool_loop_max_iterations → 用 runner 默认值."""
        from jarvis.core.chat_engine import ChatEngine
        with patch("jarvis.core.chat_engine.memory_store") as mock_store:
            mock_store.get_all_settings = AsyncMock(return_value={})
            engine = ChatEngine()
            default_max = engine.agent_loop_runner.config.max_iterations
            await engine._apply_runtime_settings()
        assert engine.agent_loop_runner.config.max_iterations == default_max


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
