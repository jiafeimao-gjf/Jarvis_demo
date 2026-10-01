# jarvis/core/file_tracker.py
"""per-conversation 文件操作追踪 — 给前端文件卡片 + 可视化用.

设计动机
--------
用户要求: 对话中文件修改/创建后, 前端能:
  1. 列出本会话所有被工具触碰的文件 (write/edit/delete/mkdir)
  2. 点击后可视化 (md/html/code 渲染)

所以后端需要记录每个 file 工具调用的操作, 按 conversation_id 聚合,
供 API 查询. Bash 工具调用产生的文件变更不追踪 (解析 shell grammar 不可靠)
— 如果用户希望追踪, 应通过 file 工具写入.

数据流:
  ChatEngine.chat()
    → 设置 current_conversation_id contextvar
    → AgentLoopRunner._exec_one() 调 file tool
    → FileOperationStrategy._write_file() 等成功路径
    → file_tracker.record(FileOp(...)) 自动按当前 conv_id 存储
    → finally: contextvar.reset(token)

API 入口:
  GET  /api/files?conversation_id=X           # 列出本会话触碰的所有文件
  GET  /api/files/content?conversation_id=X&path=Y  # 读取文件内容 (有安全约束)
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional


# ── ContextVar ─────────────────────────────────────────────────────
# ChatEngine 在每次 chat 调用前 set, AgentLoop 内的工具执行都能读到.
# asyncio 自动跨 await 边界传播, 不需要额外手动传参.
current_conversation_id: ContextVar[Optional[str]] = ContextVar(
    'jarvis_current_conversation_id', default=None
)


# ── 数据模型 ───────────────────────────────────────────────────────
@dataclass
class FileOp:
    """一条文件操作记录 (per-conversation)."""
    path: str                       # 相对 work_folder 的路径 (用户看到的)
    action: str                     # write | edit | delete | mkdir
    timestamp: str                  # ISO 8601
    size: int = 0                   # 操作后大小 (bytes); delete/mkdir 视情况
    status: str = "success"         # success | error
    error: Optional[str] = None     # status=error 时填的错误信息

    def to_dict(self) -> dict:
        return asdict(self)


# ── Tracker 主类 ───────────────────────────────────────────────────
class FileTracker:
    """per-conversation 文件操作追踪器 — 单例.

    线程安全: ContextVar 保证每个 Task 看到自己的 conv_id;
    dict 操作在 asyncio 单线程下天然安全.
    """

    def __init__(self):
        self._by_conv: dict[str, list[FileOp]] = {}

    def record(self, op: FileOp) -> None:
        """记录一条操作 — 自动取 current_conversation_id."""
        conv_id = current_conversation_id.get()
        if not conv_id:
            return  # 没有 conversation 上下文, 不记录
        self._by_conv.setdefault(conv_id, []).append(op)

    def list(self, conversation_id: str) -> list[FileOp]:
        """返回该会话所有操作 (按时间顺序, 不去重)."""
        return list(self._by_conv.get(conversation_id, []))

    def latest_by_path(self, conversation_id: str) -> list[FileOp]:
        """每个 path 只保留最新的一条操作 (UI 列表去重用).

        按 timestamp 倒序排列 — 最新操作在前, 适合 UI 列表.
        """
        latest: dict[str, FileOp] = {}
        for op in self.list(conversation_id):
            # 后写覆盖前写 — 反映当前状态 (即使同一文件被 write → delete → write)
            latest[op.path] = op
        result = list(latest.values())
        result.sort(key=lambda o: o.timestamp, reverse=True)
        return result

    def contains_path(self, conversation_id: str, path: str) -> bool:
        """检查 path 是否在本会话被触碰过 (用于内容获取的安全校验)."""
        return any(op.path == path for op in self.list(conversation_id))

    def clear(self, conversation_id: str) -> None:
        """清空某会话的记录 (归档 / 删除会话时调用)."""
        self._by_conv.pop(conversation_id, None)

    def get_stats(self, conversation_id: str) -> dict:
        """调试用统计."""
        ops = self.list(conversation_id)
        return {
            "conversation_id": conversation_id,
            "total_ops": len(ops),
            "unique_paths": len({op.path for op in ops}),
            "by_action": {
                action: sum(1 for op in ops if op.action == action)
                for action in ("write", "edit", "delete", "mkdir")
            },
        }


# 全局单例 — 直接 import 使用
file_tracker = FileTracker()


# ── 辅助 ───────────────────────────────────────────────────────────
def record_file_op(
    path: str,
    action: str,
    full_path,  # pathlib.Path, 用于读取 size
    status: str = "success",
    error: Optional[str] = None,
) -> None:
    """便捷记录函数 — FileOperationStrategy 各 op 调用.

    自动计算 size:
      - 文件: stat().st_size
      - 目录: 子文件数 (估算)
      - delete 成功: 0
    """
    size = 0
    if status == "success":
        try:
            if full_path.exists():
                if full_path.is_file():
                    size = full_path.stat().st_size
                elif full_path.is_dir():
                    size = sum(1 for _ in full_path.rglob("*") if _.is_file())
        except Exception:
            pass

    file_tracker.record(FileOp(
        path=path,
        action=action,
        timestamp=datetime.now().isoformat(),
        size=size,
        status=status,
        error=error,
    ))
