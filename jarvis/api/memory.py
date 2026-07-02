# jarvis/api/memory.py
"""记忆相关 API"""
import base64 as _b64
import os
from pathlib import Path
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, Any

from jarvis.core.mediator import mediator
from jarvis.services.skill_loader import save_prompt_file
from jarvis.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/memory", tags=["memory"])

IMAGES_DIR = Path(__file__).parent.parent.parent / "memory" / "conversations"


class MemoryRequest(BaseModel):
    """记忆请求模型"""
    key: str
    content: str
    metadata: Optional[dict] = None


class MemoryResponse(BaseModel):
    """记忆响应模型"""
    success: bool
    memory_id: Optional[str] = None


@router.post("")
async def save_memory(request: MemoryRequest):
    """保存记忆"""
    try:
        success = await mediator.memory_store.save(
            request.key,
            request.content,
            request.metadata
        )
        return MemoryResponse(success=success)
    except Exception as e:
        logger.error(f"Save memory error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("")
async def retrieve_memory(
    query: str = Query(..., description="检索查询"),
    top_k: int = Query(5, description="返回数量")
):
    """检索记忆"""
    try:
        results = await mediator.memory_store.retrieve(query, top_k)
        return {"results": results, "count": len(results)}
    except Exception as e:
        logger.error(f"Retrieve memory error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/conversation/{conversation_id}")
async def get_conversation(conversation_id: str):
    """获取对话历史"""
    try:
        conv = await mediator.memory_store.get_conversation(conversation_id)
        if conv:
            return conv
        raise HTTPException(status_code=404, detail="Conversation not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get conversation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/conversation/{conversation_id}")
async def save_conversation(conversation_id: str, request: Request):
    """保存对话历史 — 图片提取到磁盘, message 中存相对路径"""
    try:
        body = await request.json()
        user_id = body.get("user_id", "")
        messages = body.get("messages", [])
        context = body.get("context", {})
        # Accept topic only if explicitly provided; otherwise preserve existing
        topic = body.get("topic")  # may be None, "", or a string

        # Extract base64 images → save to disk → replace with path
        img_dir = IMAGES_DIR / conversation_id / "images"
        img_dir.mkdir(parents=True, exist_ok=True)
        for i, msg in enumerate(messages):
            img = msg.get("image")
            if img and img.startswith("data:image/"):
                # Parse: data:image/jpeg;base64,xxxx
                try:
                    header, b64 = img.split(",", 1)
                    fmt = header.split("/")[1].split(";")[0] or "jpeg"
                    img_bytes = _b64.b64decode(b64)
                    img_path = img_dir / f"{i}.{fmt}"
                    img_path.write_bytes(img_bytes)
                    # Replace with relative path the API can serve
                    msg["image"] = f"/api/memory/conversation/{conversation_id}/image/{i}.{fmt}"
                except Exception as e:
                    logger.warning(f"Failed to save image for msg {i}: {e}")
                    msg["image"] = None

        # Normalize topic: empty string → None (don't overwrite), valid string → save
        if topic is not None:
            topic = topic.strip()[:60] or None
        else:
            topic = None  # preserve existing

        success = await mediator.memory_store.save_conversation(
            conversation_id, user_id, messages, context, topic=topic
        )
        return {"success": success}
    except Exception as e:
        logger.error(f"Save conversation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class TopicUpdateRequest(BaseModel):
    topic: str


@router.put("/conversation/{conversation_id}/topic")
async def update_conversation_topic(conversation_id: str, request: TopicUpdateRequest):
    """手动设置/更新对话主题"""
    try:
        topic = (request.topic or "").strip()
        if not topic:
            raise HTTPException(status_code=400, detail="topic 不能为空")
        if len(topic) > 60:
            topic = topic[:60]

        # Confirm conversation exists
        existing = await mediator.memory_store.get_conversation(conversation_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Conversation not found")

        success = await mediator.memory_store.update_conversation_topic(conversation_id, topic)
        return {"success": success, "topic": topic}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Update topic error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/conversation/{conversation_id}/image/{filename}")
async def get_conversation_image(conversation_id: str, filename: str):
    """获取对话中保存的图片"""
    img_path = IMAGES_DIR / conversation_id / "images" / filename
    if not img_path.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(img_path)


@router.get("/conversations")
async def list_conversations(limit: int = Query(50, description="返回数量")):
    """列出所有对话"""
    try:
        conversations = await mediator.memory_store.list_conversations(limit)
        return {"conversations": conversations, "count": len(conversations)}
    except Exception as e:
        logger.error(f"List conversations error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/conversation/{conversation_id}")
async def delete_conversation(conversation_id: str):
    """删除对话"""
    try:
        success = await mediator.memory_store.delete_conversation(conversation_id)
        return {"success": success}
    except Exception as e:
        logger.error(f"Delete conversation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── v3: subagent 子会话 API ──────────────────────────────────────

@router.get("/conversation/{conversation_id}/sub_sessions")
async def list_sub_sessions(
    conversation_id: str,
    summary_only: bool = Query(False, description="仅返回摘要 (不含完整消息)"),
):
    """列出某主会话下的所有 subagent 子会话.

    用于主会话卡片显示 "查看 3 个子代理会话 →".
    summary_only=True 时轻量级, 用于快速渲染列表.
    """
    try:
        sessions = await mediator.memory_store.list_sub_sessions(
            parent_id=conversation_id,
            summary_only=summary_only,
        )
        count = await mediator.memory_store.count_sub_sessions(conversation_id)
        return {
            "parent_conversation_id": conversation_id,
            "count": count,
            "sessions": sessions,
        }
    except Exception as e:
        logger.error(f"List sub_sessions error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sub_session/{sub_session_id}")
async def get_sub_session(sub_session_id: str):
    """获取单个 subagent 子会话完整内容.

    用于点击主会话卡片时打开抽屉, 显示完整执行轨迹.
    """
    try:
        conv = await mediator.memory_store.get_conversation(sub_session_id)
        if not conv:
            raise HTTPException(status_code=404, detail="Sub-session not found")
        return conv
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get sub_session error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/conversation/{conversation_id}/sub_session_count")
async def get_sub_session_count(conversation_id: str):
    """获取主会话下的子会话数量 (用于主会话卡片角标)."""
    try:
        count = await mediator.memory_store.count_sub_sessions(conversation_id)
        return {"conversation_id": conversation_id, "count": count}
    except Exception as e:
        logger.error(f"Count sub_sessions error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Settings API
@router.get("/settings")
async def get_settings():
    """获取所有设置"""
    try:
        settings = await mediator.memory_store.get_all_settings()
        return {"settings": settings, "count": len(settings)}
    except Exception as e:
        logger.error(f"Get settings error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/settings/{key}")
async def get_setting(key: str):
    """获取单个设置"""
    try:
        value = await mediator.memory_store.get_setting(key)
        if value is None:
            raise HTTPException(status_code=404, detail="Setting not found")
        return {"key": key, "value": value}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get setting error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/settings/{key}")
async def save_setting(key: str, request: Request):
    """保存设置 — 同时写入 workspace 文件 (persona.md 等)"""
    try:
        value = await request.json()
        # Save to DB
        success = await mediator.memory_store.save_setting(key, value)
        # Optionally save to workspace files
        prompt_map = {
            "persona_prompt": "persona",
            "abilities_prompt": "abilities",
            "memory_prompt": "memory",
            "tools_prompt": "tools",
            "work_folder": "work_folder",
        }
        if key in prompt_map:
            save_prompt_file(prompt_map[key], str(value) if not isinstance(value, str) else value)
        return {"success": success, "key": key}
    except Exception as e:
        logger.error(f"Save setting error: {e}")
        raise HTTPException(status_code=500, detail=str(e))