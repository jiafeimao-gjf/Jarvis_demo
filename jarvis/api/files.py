# jarvis/api/files.py
"""会话文件追踪 API — 给前端文件卡片 + 可视化用.

端点:
  GET /api/files?conversation_id=X
    → 列出本会话被 file 工具触碰的所有文件 (按 path 去重, 最新状态优先)

  GET /api/files/content?conversation_id=X&path=Y
    → 读取文件内容 (有安全约束)
      - path 必须在本会话被触碰过 (否则 404, 防任意读)
      - 大小上限 1MB, 超出截断
      - 二进制文件返回 base64
"""
from __future__ import annotations

import base64
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from jarvis.core.file_tracker import file_tracker

router = APIRouter(prefix="/api/files", tags=["files"])

# 内容获取上限: 1MB
MAX_CONTENT_BYTES = 1 * 1024 * 1024


@router.get("")
async def list_session_files(
    conversation_id: str = Query(..., description="会话 ID"),
) -> dict:
    """列出本会话所有被 file 工具触碰过的文件.

    返回结构:
      {
        "conversation_id": "...",
        "files": [
          {"path": "...", "action": "write|edit|delete|mkdir",
           "timestamp": "...", "size": N, "status": "...", "error": null},
          ...
        ],
        "stats": {...}  // 统计 (write/edit/delete/mkdir 各几条)
      }
    """
    if not conversation_id:
        raise HTTPException(400, "conversation_id 不能为空")

    files = file_tracker.latest_by_path(conversation_id)
    return {
        "conversation_id": conversation_id,
        "files": [op.to_dict() for op in files],
        "stats": file_tracker.get_stats(conversation_id),
    }


@router.get("/content")
async def get_file_content(
    conversation_id: str = Query(..., description="会话 ID"),
    path: str = Query(..., description="文件相对路径 (相对于 work_folder)"),
) -> dict:
    """获取本会话某文件的当前内容.

    安全约束:
      1. path 必须在本会话被 file 工具触碰过 (否则 404)
      2. 路径必须在 work_folder 内 (防路径穿越, 复用 FileOperationStrategy)
      3. 大小 > 1MB 返回 truncated=True, content=""

    响应结构:
      {
        "path": "...",
        "size": N,
        "encoding": "utf-8" | "base64",
        "content": "...",
        "truncated": false,
        "extension": ".py",
      }
    """
    if not conversation_id or not path:
        raise HTTPException(400, "conversation_id 和 path 必填")

    # 校验 1: path 必须在本会话被触碰过
    if not file_tracker.contains_path(conversation_id, path):
        raise HTTPException(
            404,
            f"path '{path}' 未在本会话被 file 工具触碰过, 拒绝读取"
        )

    # 校验 2: 路径必须在 work_folder 内 (复用 FileOperationStrategy 的解析逻辑)
    # work_folder 默认在 cwd/workspace; 跟 file 工具解析路径保持一致
    work_folder = _resolve_work_folder()
    try:
        full_path = (Path(work_folder) / path).resolve()
        # 路径穿越检测
        try:
            full_path.relative_to(Path(work_folder).resolve())
        except ValueError:
            raise HTTPException(403, "路径在工作目录之外")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"路径解析失败: {e}")

    if not full_path.exists():
        raise HTTPException(404, f"文件已不存在: {path}")
    if not full_path.is_file():
        raise HTTPException(400, f"不是文件: {path}")

    size = full_path.stat().st_size
    ext = full_path.suffix.lower()

    # 校验 3: 大小上限
    if size > MAX_CONTENT_BYTES:
        return {
            "path": path,
            "size": size,
            "encoding": "utf-8",
            "content": "",
            "truncated": True,
            "extension": ext,
            "message": f"文件过大 ({size} bytes > {MAX_CONTENT_BYTES}), 不返回内容",
        }

    # 读取内容 — 文本用 utf-8, 二进制用 base64
    try:
        content = full_path.read_text(encoding="utf-8")
        return {
            "path": path,
            "size": size,
            "encoding": "utf-8",
            "content": content,
            "truncated": False,
            "extension": ext,
        }
    except UnicodeDecodeError:
        content_bytes = full_path.read_bytes()
        b64 = base64.b64encode(content_bytes).decode("ascii")
        return {
            "path": path,
            "size": size,
            "encoding": "base64",
            "content": b64,
            "truncated": False,
            "extension": ext,
        }


def _resolve_work_folder() -> str:
    """获取 work_folder — 从全局 mediator 实例拿, 否则用 cwd/workspace."""
    try:
        from jarvis.core.mediator import mediator
        engine = getattr(mediator, "chat_engine", None)
        if engine and getattr(engine, "work_folder", None):
            return engine.work_folder
    except Exception:
        pass
    return str(Path.cwd() / "workspace")
