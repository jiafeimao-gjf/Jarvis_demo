# tests/test_subagent.py
"""Subagent / SubagentOrchestrator / SubagentStrategy 测试."""
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from jarvis.core.entities import Step
from jarvis.core.subagent import (
    BaseSubagent,
    DispatchMode,
    DispatchRequest,
    ResearcherSubagent,
    CoderSubagent,
    ReviewerSubagent,
    SummarizerSubagent,
    PlannerSubagent,
    GeneralSubagent,
    SubagentConfig,
    SubagentOrchestrator,
    SubagentResult,
    SubagentRole,
    create_subagent,
)
from jarvis.core.task_engine import SubagentStrategy, TaskExecutor


# ── 工厂 + BaseSubagent ─────────────────────────────────────────────

class TestFactory:
    def test_known_roles(self):
        router = MagicMock()
        for role in SubagentRole:
            agent = create_subagent(role, router)
            assert agent.role == role

    def test_string_role_resolves(self):
        agent = create_subagent("researcher", MagicMock())
        assert agent.role == SubagentRole.RESEARCHER

    def test_unknown_role_falls_back_to_general(self):
        agent = create_subagent("nonexistent", MagicMock())
        assert agent.role == SubagentRole.GENERAL

    def test_config_overrides_applied(self):
        agent = create_subagent(
            SubagentRole.RESEARCHER,
            MagicMock(),
            config_overrides={"max_iterations": 7, "temperature": 0.9},
        )
        assert agent.config.max_iterations == 7
        assert agent.config.temperature == 0.9


class TestRoleSystemPrompts:
    """每个角色的 system_prompt 至少要包含任务和必要约束, 不能是空模板."""

    @pytest.mark.parametrize("role,expected_keyword", [
        (SubagentRole.RESEARCHER, "研究员"),
        (SubagentRole.CODER, "工程师"),
        (SubagentRole.REVIEWER, "评审员"),
        (SubagentRole.SUMMARIZER, "摘要员"),
        (SubagentRole.PLANNER, "规划师"),
        (SubagentRole.GENERAL, "通用"),
    ])
    def test_each_role_has_distinct_prompt(self, role, expected_keyword):
        agent = create_subagent(role, MagicMock())
        prompt = agent.build_system_prompt("test task")
        assert expected_keyword in prompt
        assert "test task" in prompt


# ── BaseSubagent.run ────────────────────────────────────────────────

class TestRunSingle:
    @pytest.mark.asyncio
    async def test_successful_run(self):
        router = MagicMock()
        resp = MagicMock(content="answer from researcher")
        router.chat = AsyncMock(return_value=resp)

        agent = ResearcherSubagent(router=router)
        result = await agent.run(task="调研 X")
        assert result.success is True
        assert result.role == SubagentRole.RESEARCHER
        assert result.output == "answer from researcher"
        assert result.iterations == 1
        assert result.error is None
        router.chat.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_with_context(self):
        router = MagicMock()
        router.chat = AsyncMock(return_value=MagicMock(content="ok"))
        agent = GeneralSubagent(router=router)

        await agent.run("task", context="some background")
        messages = router.chat.call_args.args[0]
        # system + context + user task = 3 messages
        assert len(messages) == 3
        assert "some background" in messages[1]["content"]

    @pytest.mark.asyncio
    async def test_run_handles_llm_error(self):
        router = MagicMock()
        router.chat = AsyncMock(side_effect=RuntimeError("LLM down"))

        agent = ResearcherSubagent(router=router)
        result = await agent.run(task="anything")
        assert result.success is False
        assert "LLM down" in result.error

    @pytest.mark.asyncio
    async def test_run_respects_timeout(self):
        router = MagicMock()

        async def slow_chat(*args, **kwargs):
            await asyncio.sleep(5)
            return MagicMock(content="late")

        router.chat = slow_chat
        agent = GeneralSubagent(
            router=router,
            config=SubagentConfig(
                role=SubagentRole.GENERAL,
                system_prompt="default",
                timeout=0.1,
            ),
        )
        result = await agent.run(task="anything")
        assert result.success is False
        assert result.error is not None


# ── Orchestrator: run_one / run_batch ──────────────────────────────

class TestOrchestrator:
    def _make_router(self, reply="ok"):
        r = MagicMock()
        r.chat = AsyncMock(return_value=MagicMock(content=reply))
        return r

    @pytest.mark.asyncio
    async def test_run_one(self):
        orch = SubagentOrchestrator(router=self._make_router("hi"))
        result = await orch.run_one(SubagentRole.GENERAL, "do thing")
        assert result.success
        assert result.output == "hi"

    @pytest.mark.asyncio
    async def test_run_batch_sequential_chains_context(self):
        router = self._make_router("response")
        orch = SubagentOrchestrator(router=router)

        batch = [
            DispatchRequest(SubagentRole.SUMMARIZER, "first"),
            DispatchRequest(SubagentRole.SUMMARIZER, "second"),
        ]
        out = await orch.run_batch(DispatchMode.SEQUENTIAL, batch)
        assert out.all_success
        assert len(out.results) == 2
        # second call's context should mention first call's output
        second_call = router.chat.call_args_list[1]
        msgs = second_call.args[0]
        assert any("response" in (m.get("content") or "") for m in msgs)

    @pytest.mark.asyncio
    async def test_run_batch_parallel_runs_concurrently(self):
        router = self._make_router("done")
        orch = SubagentOrchestrator(router=router)

        async def slow(*args, **kwargs):
            await asyncio.sleep(0.1)
            return MagicMock(content="done")

        router.chat = slow
        batch = [DispatchRequest(SubagentRole.RESEARCHER, f"task{i}") for i in range(5)]
        import time
        t0 = time.time()
        out = await orch.run_batch(DispatchMode.PARALLEL, batch)
        elapsed = time.time() - t0
        assert len(out.results) == 5
        # Parallel should be much faster than 5 * 0.1 = 0.5s
        assert elapsed < 0.4

    @pytest.mark.asyncio
    async def test_run_batch_map_reduce_includes_reduced_output(self):
        router = self._make_router("summary text")
        orch = SubagentOrchestrator(router=router)

        batch = [
            DispatchRequest(SubagentRole.RESEARCHER, "t1"),
            DispatchRequest(SubagentRole.RESEARCHER, "t2"),
        ]
        out = await orch.run_batch(
            DispatchMode.MAP_REDUCE, batch,
            reduce_prompt="combine",
        )
        assert out.reduced_output is not None
        # router.chat was called for reduce
        assert router.chat.call_count == 3  # 2 map + 1 reduce

    @pytest.mark.asyncio
    async def test_run_batch_empty(self):
        orch = SubagentOrchestrator(router=self._make_router())
        out = await orch.run_batch(DispatchMode.PARALLEL, [])
        assert out.results == []


# ── SubagentStrategy (tool dispatch) ───────────────────────────────

class TestSubagentStrategy:
    @pytest.mark.asyncio
    async def test_dispatch_requires_orchestrator(self):
        s = SubagentStrategy()
        step = Step(tool="subagent", params={"role": "researcher", "task": "x"})
        result = await s.execute(step)
        assert result["status"] == "error"
        assert "未注入" in result["message"]

    @pytest.mark.asyncio
    async def test_single_task_dispatch(self):
        router = MagicMock()
        router.chat = AsyncMock(return_value=MagicMock(content="answer"))
        orch = SubagentOrchestrator(router=router)
        s = SubagentStrategy(orchestrator=orch)

        step = Step(tool="subagent", params={
            "role": "researcher", "task": "调研 X",
        })
        result = await s.execute(step)
        assert result["status"] == "success"
        assert result["role"] == "researcher"
        assert result["output"] == "answer"
        assert "elapsed_ms" in result

    @pytest.mark.asyncio
    async def test_batch_task_dispatch_parallel(self):
        router = MagicMock()
        router.chat = AsyncMock(return_value=MagicMock(content="ok"))
        orch = SubagentOrchestrator(router=router)
        s = SubagentStrategy(orchestrator=orch)

        step = Step(tool="subagent", params={
            "mode": "parallel",
            "tasks": [
                {"role": "researcher", "task": "t1"},
                {"role": "summarizer", "task": "t2"},
            ],
        })
        result = await s.execute(step)
        assert result["status"] == "success"
        assert result["mode"] == "parallel"
        assert len(result["results"]) == 2

    @pytest.mark.asyncio
    async def test_invalid_role_falls_back_to_general(self):
        router = MagicMock()
        router.chat = AsyncMock(return_value=MagicMock(content="ok"))
        orch = SubagentOrchestrator(router=router)
        s = SubagentStrategy(orchestrator=orch)

        step = Step(tool="subagent", params={"role": "mystery", "task": "x"})
        result = await s.execute(step)
        assert result["role"] == "general"
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_empty_batch(self):
        router = MagicMock()
        router.chat = AsyncMock(return_value=MagicMock(content="ok"))
        orch = SubagentOrchestrator(router=router)
        s = SubagentStrategy(orchestrator=orch)

        step = Step(tool="subagent", params={"mode": "parallel", "tasks": []})
        result = await s.execute(step)
        assert result["status"] == "error"
        assert "为空" in result["message"]


# ── TaskExecutor 注册集成 ──────────────────────────────────────────

class TestTaskExecutorRegistration:
    def test_register_adds_strategy(self):
        executor = TaskExecutor()
        assert "subagent" not in executor.strategies
        orch = SubagentOrchestrator(router=MagicMock())
        executor.register_subagent(orch)
        assert "subagent" in executor.strategies
        assert isinstance(executor.strategies["subagent"], SubagentStrategy)

    def test_register_rejects_non_orchestrator(self):
        executor = TaskExecutor()
        with pytest.raises(TypeError):
            executor.register_subagent("not an orchestrator")

    @pytest.mark.asyncio
    async def test_executor_dispatches_to_subagent_strategy(self):
        executor = TaskExecutor()
        router = MagicMock()
        router.chat = AsyncMock(return_value=MagicMock(content="dispatched"))
        orch = SubagentOrchestrator(router=router)
        executor.register_subagent(orch)

        step = Step(tool="subagent", params={
            "role": "coder", "task": "写 hello world",
        })
        result = await executor.execute_step(step)
        assert result["status"] == "success"
        assert result["output"] == "dispatched"


# ── 序列化 (to_dict) ───────────────────────────────────────────────

class TestSerialization:
    def test_subagent_result_to_dict(self):
        r = SubagentResult(
            role=SubagentRole.RESEARCHER,
            task="t",
            success=True,
            output="o",
            iterations=2,
            elapsed_ms=123.4,
        )
        d = r.to_dict()
        assert d["role"] == "researcher"
        assert d["iterations"] == 2
        assert d["elapsed_ms"] == 123.4

    @pytest.mark.asyncio
    async def test_batch_to_dict(self):
        router = MagicMock()
        router.chat = AsyncMock(return_value=MagicMock(content="ok"))
        orch = SubagentOrchestrator(router=router)
        batch = await orch.run_batch(
            DispatchMode.PARALLEL,
            [DispatchRequest(SubagentRole.GENERAL, "t1")],
        )
        d = batch.to_dict()
        assert d["mode"] == "parallel"
        assert d["count"] == 1
        assert d["all_success"] is True