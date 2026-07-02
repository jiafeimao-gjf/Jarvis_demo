# tests/test_subagent_session.py
"""v3 subagent 独立会话测试 — DB Schema / MemoryStore / BaseSubagent 持久化."""
import asyncio
import json
import os
import shutil
import tempfile
import pytest
from unittest.mock import AsyncMock, MagicMock

from jarvis.core.entities import Conversation, Message
from jarvis.core.memory_store import (
    SQLiteMemoryRepository,
    MemoryStore,
    memory_store,
)
from jarvis.core.subagent import (
    BaseSubagent,
    GeneralSubagent,
    ResearcherSubagent,
    SubagentOrchestrator,
    SubagentRole,
    DispatchMode,
    DispatchRequest,
    create_subagent,
)


# ── Helpers ────────────────────────────────────────────────────────

@pytest.fixture
def temp_db():
    """每个测试用独立的临时 DB, 测试完清理."""
    tmpdir = tempfile.mkdtemp(prefix="jarvis_test_")
    db_path = os.path.join(tmpdir, "test.db")
    yield db_path
    shutil.rmtree(tmpdir, ignore_errors=True)


def make_conversation(conv_id: str = "parent-conv", messages: int = 0) -> Conversation:
    conv = Conversation(conversation_id=conv_id, user_id="tester")
    for i in range(messages):
        conv.add_message("user", f"msg {i}")
    return conv


def make_router(content: str = "test output") -> MagicMock:
    r = MagicMock()
    r.chat = AsyncMock(return_value=MagicMock(
        content=content, thinking="", content_blocks=None,
    ))
    return r


# ── Conversation 实体扩展字段 ─────────────────────────────────────

class TestConversationExtension:
    def test_defaults_to_main_session(self):
        conv = Conversation()
        assert conv.session_kind == "main"
        assert conv.parent_conversation_id is None
        assert conv.subagent_role is None
        assert conv.subagent_task is None
        assert conv.is_subagent() is False

    def test_subagent_conversation(self):
        conv = Conversation(
            parent_conversation_id="parent-id",
            session_kind="subagent",
            subagent_role="researcher",
            subagent_task="调研 X",
        )
        assert conv.is_subagent() is True

    def test_to_dict_includes_new_fields(self):
        conv = Conversation(
            conversation_id="c1",
            parent_conversation_id="p1",
            session_kind="subagent",
            subagent_role="coder",
            subagent_task="task",
            metadata={"mode": "parallel"},
        )
        d = conv.to_dict()
        assert d["parent_conversation_id"] == "p1"
        assert d["session_kind"] == "subagent"
        assert d["subagent_role"] == "coder"
        assert d["subagent_task"] == "task"
        assert d["metadata"] == {"mode": "parallel"}


# ── DB Schema 迁移 ────────────────────────────────────────────────

class TestDBSchemaMigration:
    def test_new_columns_exist(self, temp_db):
        repo = SQLiteMemoryRepository(db_path=temp_db)
        import sqlite3
        with sqlite3.connect(temp_db) as conn:
            cursor = conn.execute("PRAGMA table_info(conversations)")
            cols = {row[1] for row in cursor.fetchall()}
        for col in [
            "parent_conversation_id",
            "session_kind",
            "subagent_role",
            "subagent_task",
            "triggered_by_message_id",
            "metadata",
        ]:
            assert col in cols, f"缺少列: {col}"

    def test_indexes_created(self, temp_db):
        repo = SQLiteMemoryRepository(db_path=temp_db)
        import sqlite3
        with sqlite3.connect(temp_db) as conn:
            cursor = conn.execute("PRAGMA index_list(conversations)")
            idx_names = {row[1] for row in cursor.fetchall()}
        assert "idx_conv_parent" in idx_names
        assert "idx_conv_kind" in idx_names


# ── MemoryStore save_sub_session / list_sub_sessions ──────────────

class TestSubSessionCRUD:
    @pytest.mark.asyncio
    async def test_save_and_get_sub_session(self, temp_db):
        repo = SQLiteMemoryRepository(db_path=temp_db)
        sub = Conversation(
            conversation_id="sub-1",
            user_id="alice",
            topic="[researcher] 调研 X",
            parent_conversation_id="parent-1",
            session_kind="subagent",
            subagent_role="researcher",
            subagent_task="调研 X",
            metadata={"mode": "single"},
        )
        sub.add_message("user", "调研 X")
        sub.add_message("assistant", "result text", thinking="think...")
        ok = await repo.save_sub_session(sub)
        assert ok is True

        loaded = await repo.get_conversation("sub-1")
        assert loaded is not None
        assert loaded["parent_conversation_id"] == "parent-1"
        assert loaded["session_kind"] == "subagent"
        assert loaded["subagent_role"] == "researcher"
        assert loaded["subagent_task"] == "调研 X"
        assert loaded["metadata"] == {"mode": "single"}
        assert len(loaded["messages"]) == 2
        assert loaded["messages"][1]["thinking"] == "think..."

    @pytest.mark.asyncio
    async def test_list_sub_sessions(self, temp_db):
        repo = SQLiteMemoryRepository(db_path=temp_db)
        # 创建 3 个子会话
        for i in range(3):
            sub = Conversation(
                conversation_id=f"sub-{i}",
                user_id="alice",
                parent_conversation_id="parent-1",
                session_kind="subagent",
                subagent_role="researcher" if i < 2 else "coder",
                subagent_task=f"task {i}",
            )
            await repo.save_sub_session(sub)
        # 创建 1 个不相关子会话
        other = Conversation(
            conversation_id="sub-other",
            parent_conversation_id="parent-other",
            session_kind="subagent",
        )
        await repo.save_sub_session(other)

        results = await repo.list_sub_sessions("parent-1")
        assert len(results) == 3
        for r in results:
            assert r["parent_conversation_id"] == "parent-1"

    @pytest.mark.asyncio
    async def test_list_summary_only(self, temp_db):
        repo = SQLiteMemoryRepository(db_path=temp_db)
        sub = Conversation(
            conversation_id="sub-s",
            parent_conversation_id="p",
            session_kind="subagent",
            subagent_role="coder",
            subagent_task="code task",
        )
        sub.add_message("user", "x" * 1000)
        await repo.save_sub_session(sub)

        summaries = await repo.list_sub_sessions("p", summary_only=True)
        assert len(summaries) == 1
        # summary_only 不返回 messages (为空列表)
        assert summaries[0].get("messages") == []
        # 但保留 subagent 摘要字段
        assert summaries[0]["subagent_role"] == "coder"
        assert summaries[0]["subagent_task"] == "code task"

    @pytest.mark.asyncio
    async def test_count_sub_sessions(self, temp_db):
        repo = SQLiteMemoryRepository(db_path=temp_db)
        for i in range(5):
            await repo.save_sub_session(Conversation(
                conversation_id=f"s-{i}",
                parent_conversation_id="p",
                session_kind="subagent",
            ))
        n = await repo.count_sub_sessions("p")
        assert n == 5

    @pytest.mark.asyncio
    async def test_list_conversations_excludes_subagents_by_default(self, temp_db):
        repo = SQLiteMemoryRepository(db_path=temp_db)
        main = Conversation(conversation_id="main-1", user_id="u")
        main.add_message("user", "hi")
        await repo.save_conversation("main-1", "u", [{"role": "user", "content": "hi"}], {})

        sub = Conversation(
            conversation_id="sub-1",
            parent_conversation_id="main-1",
            session_kind="subagent",
        )
        await repo.save_sub_session(sub)

        # 默认应该不返回 subagent
        result = await repo.list_conversations()
        assert len(result) == 1
        assert result[0]["conversation_id"] == "main-1"

        # include_subagents=True 时返回全部
        result_all = await repo.list_conversations(include_subagents=True)
        assert len(result_all) == 2


# ── BaseSubagent 自动持久化 ──────────────────────────────────────

class TestBaseSubagentPersistence:
    @pytest.mark.asyncio
    async def test_no_parent_no_persistence(self):
        """不注入 parent/store 时, 不创建子会话, sub_session_id=None."""
        agent = GeneralSubagent(router=make_router("ok"))
        result = await agent.run(task="anything")
        assert result.success
        assert result.sub_session_id is None

    @pytest.mark.asyncio
    async def test_creates_sub_session_when_parent_provided(self, temp_db):
        store = MemoryStore.__new__(MemoryStore)  # bypass __init__
        store.sqlite_repo = SQLiteMemoryRepository(db_path=temp_db)

        parent = make_conversation("parent-1")
        agent = GeneralSubagent(
            router=make_router("subagent answer"),
            parent_conversation=parent,
            message_store=store,
        )
        result = await agent.run(task="do something")

        assert result.success
        assert result.sub_session_id is not None
        # 持久化校验
        loaded = await store.sqlite_repo.get_conversation(result.sub_session_id)
        assert loaded is not None
        assert loaded["parent_conversation_id"] == "parent-1"
        assert loaded["session_kind"] == "subagent"
        assert loaded["subagent_role"] == "general"
        assert loaded["subagent_task"] == "do something"
        # 应该有 user + assistant 两条消息
        assert len(loaded["messages"]) == 2
        assert loaded["messages"][0]["role"] == "user"
        assert loaded["messages"][0]["content"] == "do something"
        assert loaded["messages"][1]["role"] == "assistant"
        assert loaded["messages"][1]["content"] == "subagent answer"

    @pytest.mark.asyncio
    async def test_records_thinking(self, temp_db):
        store = MemoryStore.__new__(MemoryStore)
        store.sqlite_repo = SQLiteMemoryRepository(db_path=temp_db)

        router = MagicMock()
        router.chat = AsyncMock(return_value=MagicMock(
            content="final",
            thinking="chain of thought...",
        ))

        parent = make_conversation("p")
        agent = ResearcherSubagent(
            router=router,
            parent_conversation=parent,
            message_store=store,
        )
        result = await agent.run(task="research x")
        loaded = await store.sqlite_repo.get_conversation(result.sub_session_id)
        assert loaded["messages"][1]["thinking"] == "chain of thought..."

    @pytest.mark.asyncio
    async def test_persists_even_on_failure(self, temp_db):
        """LLM 失败时, 也应持久化记录失败状态."""
        store = MemoryStore.__new__(MemoryStore)
        store.sqlite_repo = SQLiteMemoryRepository(db_path=temp_db)

        router = MagicMock()
        router.chat = AsyncMock(side_effect=RuntimeError("LLM boom"))

        parent = make_conversation("p")
        agent = GeneralSubagent(
            router=router,
            parent_conversation=parent,
            message_store=store,
        )
        result = await agent.run(task="will fail")

        assert result.success is False
        assert result.sub_session_id is not None
        loaded = await store.sqlite_repo.get_conversation(result.sub_session_id)
        assert loaded["messages"][1]["content"].startswith("[执行失败]")

    @pytest.mark.asyncio
    async def test_topic_truncated_to_60_chars(self, temp_db):
        store = MemoryStore.__new__(MemoryStore)
        store.sqlite_repo = SQLiteMemoryRepository(db_path=temp_db)
        parent = make_conversation("p")
        agent = GeneralSubagent(
            router=make_router("x"),
            parent_conversation=parent,
            message_store=store,
        )
        long_task = "a" * 100
        result = await agent.run(task=long_task)
        loaded = await store.sqlite_repo.get_conversation(result.sub_session_id)
        # topic 形如 "[general] aaa..." 自动截断
        assert len(loaded["topic"]) <= 60


# ── SubagentOrchestrator 注入 parent / store ──────────────────────

class TestOrchestratorWithPersistence:
    @pytest.mark.asyncio
    async def test_run_one_creates_sub_session(self, temp_db):
        store = MemoryStore.__new__(MemoryStore)
        store.sqlite_repo = SQLiteMemoryRepository(db_path=temp_db)
        parent = make_conversation("parent-x")

        orch = SubagentOrchestrator(
            router=make_router("answer"),
            parent_conversation=parent,
            message_store=store,
        )
        result = await orch.run_one(SubagentRole.GENERAL, "task")
        assert result.sub_session_id is not None

        # DB 校验
        sub_count = await store.count_sub_sessions("parent-x")
        assert sub_count == 1

    @pytest.mark.asyncio
    async def test_run_batch_creates_multiple_sub_sessions(self, temp_db):
        store = MemoryStore.__new__(MemoryStore)
        store.sqlite_repo = SQLiteMemoryRepository(db_path=temp_db)
        parent = make_conversation("parent-batch")

        orch = SubagentOrchestrator(
            router=make_router("ok"),
            parent_conversation=parent,
            message_store=store,
        )
        batch = [
            DispatchRequest(SubagentRole.RESEARCHER, "t1"),
            DispatchRequest(SubagentRole.CODER, "t2"),
            DispatchRequest(SubagentRole.REVIEWER, "t3"),
        ]
        result = await orch.run_batch(DispatchMode.PARALLEL, batch)
        assert len(result.results) == 3
        for r in result.results:
            assert r.sub_session_id is not None
        # DB 中应该有 3 条
        n = await store.count_sub_sessions("parent-batch")
        assert n == 3

    @pytest.mark.asyncio
    async def test_no_parent_no_persistence(self):
        """不注入 parent/store 时, run_batch 也照常工作, 但不持久化."""
        orch = SubagentOrchestrator(router=make_router("x"))
        batch = [
            DispatchRequest(SubagentRole.GENERAL, "t1"),
        ]
        result = await orch.run_batch(DispatchMode.PARALLEL, batch)
        for r in result.results:
            assert r.sub_session_id is None


# ── SubagentStrategy 返回值带 sub_session_id ─────────────────────

class TestSubagentStrategySubSessionId:
    @pytest.mark.asyncio
    async def test_single_returns_sub_session_id(self, temp_db):
        from jarvis.core.entities import Step
        from jarvis.core.task_engine import SubagentStrategy

        store = MemoryStore.__new__(MemoryStore)
        store.sqlite_repo = SQLiteMemoryRepository(db_path=temp_db)
        parent = make_conversation("p")
        orch = SubagentOrchestrator(
            router=make_router("ok"),
            parent_conversation=parent,
            message_store=store,
        )
        strategy = SubagentStrategy(orchestrator=orch)

        step = Step(tool="subagent", params={
            "role": "general", "task": "test task",
        })
        result = await strategy.execute(step)
        assert "sub_session_id" in result
        assert result["sub_session_id"] is not None

    @pytest.mark.asyncio
    async def test_batch_returns_sub_session_ids_list(self, temp_db):
        from jarvis.core.entities import Step
        from jarvis.core.task_engine import SubagentStrategy

        store = MemoryStore.__new__(MemoryStore)
        store.sqlite_repo = SQLiteMemoryRepository(db_path=temp_db)
        parent = make_conversation("p-batch")
        orch = SubagentOrchestrator(
            router=make_router("ok"),
            parent_conversation=parent,
            message_store=store,
        )
        strategy = SubagentStrategy(orchestrator=orch)

        step = Step(tool="subagent", params={
            "mode": "parallel",
            "tasks": [
                {"role": "researcher", "task": "t1"},
                {"role": "coder", "task": "t2"},
            ],
        })
        result = await strategy.execute(step)
        assert "sub_session_ids" in result
        assert len(result["sub_session_ids"]) == 2
        # 每个 results 项也应有 sub_session_id
        for r in result["results"]:
            assert r["sub_session_id"] is not None