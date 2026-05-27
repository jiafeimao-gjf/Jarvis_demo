# jarvis/api/memory.py
"""记忆相关 API"""
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel
from typing import Optional, Any

from jarvis.core.mediator import mediator
from jarvis.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/memory", tags=["memory"])


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


class ConversationRequest(BaseModel):
    """保存对话请求模型"""
    user_id: str = ""
    messages: list = []
    context: dict = {}


@router.post("/conversation/{conversation_id}")
async def save_conversation(conversation_id: str, request: ConversationRequest):
    """保存对话历史"""
    try:
        success = await mediator.memory_store.save_conversation(
            conversation_id, request.user_id, request.messages, request.context
        )
        return {"success": success}
    except Exception as e:
        logger.error(f"Save conversation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
    """保存设置"""
    try:
        value = await request.json()
        success = await mediator.memory_store.save_setting(key, value)
        return {"success": success, "key": key}
    except Exception as e:
        logger.error(f"Save setting error: {e}")
        raise HTTPException(status_code=500, detail=str(e))