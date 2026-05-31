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
    user_id: Optional[str] = None
    model: Optional[str] = None
    stream: bool = True
    force_refresh_models: bool = False
    # 可选：传递完整对话历史以支持上下文
    messages: Optional[list[dict]] = None


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
async def list_models(force_refresh: bool = False):
    """获取可用的 AI 模型列表"""
    try:
        models = await mediator.chat_engine.list_models(force_refresh=force_refresh)
        return {"models": models}
    except Exception as e:
        logger.error(f"List models error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stream")
async def chat_stream(request: ChatRequest):
    """流式对话响应"""
    async def event_generator():
        import time as _time
        t_start = _time.time()
        try:
            # 发送正在思考状态
            yield {
                "event": "status",
                "data": json.dumps({"type": "status", "content": "thinking"})
            }

            # 如果提供了完整消息历史，使用它；否则使用 conversation_id
            if request.messages is not None:
                # 使用传入的消息历史
                full_response = ""
                first_token = True
                async for content in mediator.chat_engine.stream_chat_with_messages(
                    request.message,
                    request.messages,
                    request.model,
                    request.conversation_id,
                    request.user_id
                ):
                    if first_token:
                        logger.info(f"[SSE] 首个数据到达, 耗时={(_time.time()-t_start)*1000:.0f}ms")
                        first_token = False
                    # JSON events: tool_call, tool_result, thinking, thinking_start, thinking_end
                    if content.startswith('{'):
                        try:
                            evt = json.loads(content)
                            evt_type = evt.get("type", "unknown")
                            yield {
                                "event": "tool" if evt_type.startswith("tool") else "token",
                                "data": content
                            }
                        except json.JSONDecodeError:
                            full_response += content
                            yield {
                                "event": "token",
                                "data": json.dumps({"type": "token", "content": content})
                            }
                    else:
                        full_response += content
                        yield {
                            "event": "token",
                            "data": json.dumps({"type": "token", "content": content})
                        }
            else:
                # 使用 conversation_id 获取历史
                full_response = ""
                async for content in mediator.chat_engine.stream_chat(
                    request.message,
                    request.conversation_id,
                    request.model,
                    request.user_id
                ):
                    # 检查是否是 JSON 事件（tool_call 或 tool_result）
                    if content.startswith('{'):
                        # 直接发送 JSON 事件
                        yield {
                            "event": "tool",
                            "data": content
                        }
                    else:
                        # 普通文本 token
                        full_response += content
                        yield {
                            "event": "token",
                            "data": json.dumps({"type": "token", "content": content})
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