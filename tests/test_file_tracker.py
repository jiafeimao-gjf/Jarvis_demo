# tests/test_file_tracker.py
"""FileTracker 测试 — per-conversation 文件操作追踪."""
from pathlib import Path
import pytest

from jarvis.core.file_tracker import (
    FileTracker,
    FileOp,
    file_tracker,
    current_conversation_id,
    record_file_op,
)


@pytest.fixture
def tracker():
    return FileTracker()


@pytest.fixture(autouse=True)
def _reset_state():
    """每个测试前后重置 contextvar + 全局 tracker, 避免跨测试泄漏."""
    current_conversation_id.set(None)
    file_tracker._by_conv.clear()
    yield
    current_conversation_id.set(None)
    file_tracker._by_conv.clear()


# ── 单条记录 ─────────────────────────────────────────────────────────

class TestRecord:
    def test_record_without_conv_id_is_noop(self, tracker):
        """没设置 conv_id 时, record 静默跳过 (file tool 在工具循环外调用)."""
        op = FileOp(path="x.py", action="write", timestamp="2026-10-01T00:00:00")
        tracker.record(op)
        assert tracker.list("any-id") == []

    def test_record_with_conv_id_stores(self, tracker):
        current_conversation_id.set("conv-1")
        op = FileOp(path="a.py", action="write", timestamp="2026-10-01T00:00:00")
        tracker.record(op)
        ops = tracker.list("conv-1")
        assert len(ops) == 1
        assert ops[0].path == "a.py"

    def test_multiple_ops_per_conv(self, tracker):
        current_conversation_id.set("conv-1")
        for i in range(3):
            tracker.record(FileOp(path=f"f{i}.py", action="write", timestamp=f"2026-10-01T00:00:0{i}"))
        assert len(tracker.list("conv-1")) == 3

    def test_separate_conversations(self, tracker):
        current_conversation_id.set("conv-1")
        tracker.record(FileOp(path="a.py", action="write", timestamp="t1"))
        current_conversation_id.set("conv-2")
        tracker.record(FileOp(path="b.py", action="write", timestamp="t2"))
        assert len(tracker.list("conv-1")) == 1
        assert len(tracker.list("conv-2")) == 1
        assert tracker.list("conv-1")[0].path == "a.py"


# ── latest_by_path (UI 列表去重) ────────────────────────────────────

class TestLatestByPath:
    def test_empty(self, tracker):
        assert tracker.latest_by_path("nonexistent") == []

    def test_single_op_per_path(self, tracker):
        current_conversation_id.set("conv-1")
        tracker.record(FileOp(path="a.py", action="write", timestamp="2026-10-01T00:00:00"))
        latest = tracker.latest_by_path("conv-1")
        assert len(latest) == 1
        assert latest[0].path == "a.py"

    def test_keeps_latest_per_path(self, tracker):
        """同一 path 多次操作, 只保留最后一条."""
        current_conversation_id.set("conv-1")
        tracker.record(FileOp(path="a.py", action="write", timestamp="2026-10-01T00:00:00", size=10))
        tracker.record(FileOp(path="a.py", action="edit", timestamp="2026-10-01T00:00:01", size=20))
        tracker.record(FileOp(path="a.py", action="delete", timestamp="2026-10-01T00:00:02"))
        latest = tracker.latest_by_path("conv-1")
        assert len(latest) == 1
        assert latest[0].action == "delete"

    def test_sorted_by_timestamp_desc(self, tracker):
        """按时间倒序 — 最新在前."""
        current_conversation_id.set("conv-1")
        tracker.record(FileOp(path="a.py", action="write", timestamp="2026-10-01T00:00:00"))
        tracker.record(FileOp(path="b.py", action="write", timestamp="2026-10-01T00:00:02"))
        tracker.record(FileOp(path="c.py", action="write", timestamp="2026-10-01T00:00:01"))
        latest = tracker.latest_by_path("conv-1")
        assert [op.path for op in latest] == ["b.py", "c.py", "a.py"]


# ── contains_path (API 安全校验) ────────────────────────────────────

class TestContainsPath:
    def test_true(self, tracker):
        current_conversation_id.set("conv-1")
        tracker.record(FileOp(path="a.py", action="write", timestamp="t1"))
        assert tracker.contains_path("conv-1", "a.py") is True

    def test_false(self, tracker):
        current_conversation_id.set("conv-1")
        tracker.record(FileOp(path="a.py", action="write", timestamp="t1"))
        assert tracker.contains_path("conv-1", "b.py") is False
        assert tracker.contains_path("conv-2", "a.py") is False


# ── clear / stats ────────────────────────────────────────────────────

class TestClearAndStats:
    def test_clear_removes_conv(self, tracker):
        current_conversation_id.set("conv-1")
        tracker.record(FileOp(path="a.py", action="write", timestamp="t1"))
        assert len(tracker.list("conv-1")) == 1
        tracker.clear("conv-1")
        assert len(tracker.list("conv-1")) == 0

    def test_clear_nonexistent_is_safe(self, tracker):
        tracker.clear("nonexistent")  # 不抛

    def test_stats_by_action(self, tracker):
        current_conversation_id.set("conv-1")
        tracker.record(FileOp(path="a.py", action="write", timestamp="t1"))
        tracker.record(FileOp(path="b.py", action="edit", timestamp="t2"))
        tracker.record(FileOp(path="c.py", action="delete", timestamp="t3"))
        tracker.record(FileOp(path="d/", action="mkdir", timestamp="t4"))
        stats = tracker.get_stats("conv-1")
        assert stats["total_ops"] == 4
        assert stats["unique_paths"] == 4
        assert stats["by_action"]["write"] == 1
        assert stats["by_action"]["edit"] == 1
        assert stats["by_action"]["delete"] == 1
        assert stats["by_action"]["mkdir"] == 1


# ── record_file_op helper ───────────────────────────────────────────

class TestRecordHelper:
    def test_writes_file_size(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world", encoding="utf-8")
        current_conversation_id.set("conv-1")
        record_file_op("test.txt", "write", f)
        ops = file_tracker.list("conv-1")
        assert len(ops) == 1
        assert ops[0].size == len("hello world")
        assert ops[0].status == "success"

    def test_delete_size_zero(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("x", encoding="utf-8")
        current_conversation_id.set("conv-1")
        # 模拟删除后路径已不存在
        f.unlink()
        record_file_op("test.txt", "delete", f)
        ops = file_tracker.list("conv-1")
        assert ops[0].size == 0
        assert ops[0].status == "success"

    def test_mkdir_directory_size(self, tmp_path):
        d = tmp_path / "subdir"
        d.mkdir()
        (d / "a.txt").write_text("a")
        (d / "b.txt").write_text("b")
        current_conversation_id.set("conv-1")
        record_file_op("subdir/", "mkdir", d)
        ops = file_tracker.list("conv-1")
        # size = 子文件数
        assert ops[0].size == 2

    def test_error_status(self, tmp_path):
        f = tmp_path / "nonexistent.txt"
        current_conversation_id.set("conv-1")
        record_file_op("nonexistent.txt", "write", f, status="error", error="permission denied")
        ops = file_tracker.list("conv-1")
        assert ops[0].status == "error"
        assert ops[0].error == "permission denied"
        assert ops[0].size == 0

    def test_no_conv_id_noop(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("x")
        record_file_op("test.txt", "write", f)  # no current_conversation_id set
        assert file_tracker.list("any-conv") == []


# ── FileOp 序列化 ───────────────────────────────────────────────────

class TestFileOpToDict:
    def test_round_trip(self):
        op = FileOp(
            path="src/main.py",
            action="write",
            timestamp="2026-10-01T00:00:00",
            size=1024,
            status="success",
            error=None,
        )
        d = op.to_dict()
        assert d == {
            "path": "src/main.py",
            "action": "write",
            "timestamp": "2026-10-01T00:00:00",
            "size": 1024,
            "status": "success",
            "error": None,
        }
