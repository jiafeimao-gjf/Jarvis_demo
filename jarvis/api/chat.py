# jarvis/api/chat.py
"""对话相关 API"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from sse_starlette import EventSourceResponse
import json

from jarvis.core.mediator import mediator
from jarvis.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    """对话请求模型"""
    message: str
    conversation_id: Optional[str] = None
    model: Optional[str] = None
    stream: bool = True


class ChatResponse(BaseModel):
    """对话响应模型"""
    text: str
    response: str
    conversation_id: Optional[str] = None


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """文字对话"""
    try:
        result = await mediator.process_chat(
            request.message,
            request.conversation_id,
            request.model
        )
        return ChatResponse(
            text=result.get("text", request.message),
            response=result.get("response", ""),
            conversation_id=result.get("conversation_id")
        )
    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/models")
async def list_models():
    """获取可用的 AI 模型列表"""
    try:
        models = await mediator.chat_engine.list_models()
        return {"models": models}
    except Exception as e:
        logger.error(f"List models error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stream")
async def chat_stream(request: ChatRequest):
    """流式对话响应"""
    async def event_generator():
        try:
            # 发送正在思考状态
            yield {
                "event": "status",
                "data": json.dumps({"type": "status", "content": "thinking"})
            }

            # 流式处理
            full_response = ""
            async for token in mediator.chat_engine.stream_chat(
                request.message,
                request.conversation_id,
                request.model
            ):
                full_response += token
                yield {
                    "event": "token",
                    "data": json.dumps({"type": "token", "content": token})
                }

            # 发送完成状态
            yield {
                "event": "done",
                "data": json.dumps({
                    "type": "done",
                    "content": full_response,
                    "conversation_id": mediator.chat_engine.current_conversation.conversation_id
                    if mediator.chat_engine.current_conversation else None
                })
            }
        except Exception as e:
            logger.error(f"Stream chat error: {e}")
            yield {
                "event": "error",
                "data": json.dumps({"type": "error", "content": str(e)})
            }
            return  # Stop streaming after error

    return EventSourceResponse(event_generator())