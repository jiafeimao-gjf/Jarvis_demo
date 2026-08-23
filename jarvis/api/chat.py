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
    provider_id: Optional[str] = None
    # 可选：是否启用 TTS（声音克隆 / 浏览器降级）。默认 True
    enable_tts: bool = True


class ChatResponse(BaseModel):
    """对话响应模型"""
    text: str
    response: str
    conversation_id: Optional[str] = None
    topic: Optional[str] = None  # 自动生成/用户编辑的对话主题


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
            conversation_id=result.get("conversation_id"),
            topic=result.get("topic"),
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
    """流式对话响应 + 可选 TTS（声音克隆 / 浏览器降级）。

    enable_tts=True 时，每累积到一句话就调 F5-TTS 合成 PCM 推 SSE audio 事件。
    F5-TTS 不可用 → 自动改推 tts_fallback 事件，前端用浏览器 SpeechSynthesis 兜底。
    """
    from jarvis.config import settings as app_settings
    from jarvis.services.tts import _find_split, encode_pcm_chunk, f5_tts

    enable_tts = bool(request.enable_tts)
    can_clone = bool(enable_tts and f5_tts.available)
    min_chars = app_settings.voice_clone.sentence_min_chars
    max_chars = app_settings.voice_clone.sentence_max_chars

    # 状态 (list-as-mutable-box 方便闭包修改)
    sentence_buf = [""]
    sentence_idx = [0]

    async def push_token_events(token: str):
        """async generator: 处理一个文本 token, 累加 + 切句 + 触发 TTS, yield SSE 事件 dict"""
        sentence_buf[0] += token
        yield {"event": "token", "data": json.dumps({"type": "token", "content": token})}
        # 句切分循环
        while True:
            idx = _find_split(sentence_buf[0], min_chars, max_chars)
            if idx is None:
                break
            sentence = sentence_buf[0][:idx].strip()
            sentence_buf[0] = sentence_buf[0][idx:]
            if not sentence:
                continue
            # TTS 触发
            if can_clone:
                try:
                    async for pcm in f5_tts.synthesize_to_pcm(sentence):
                        yield {
                            "event": "audio",
                            "data": encode_pcm_chunk(sentence_idx[0], pcm),
                        }
                    sentence_idx[0] += 1
                except Exception as e:
                    logger.warning(f"[TTS] 句合成失败，降级: {e}")
                    yield {
                        "event": "tts_fallback",
                        "data": json.dumps({"type": "tts_fallback", "text": sentence}),
                    }
            else:
                yield {
                    "event": "tts_fallback",
                    "data": json.dumps({"type": "tts_fallback", "text": sentence}),
                }

    async def flush_tail_events():
        """async generator: 流结束时 flush 残余 buffer, yield SSE 事件"""
        tail = sentence_buf[0].strip()
        sentence_buf[0] = ""
        if not tail:
            return
        if can_clone:
            try:
                async for pcm in f5_tts.synthesize_to_pcm(tail):
                    yield {
                        "event": "audio",
                        "data": encode_pcm_chunk(sentence_idx[0], pcm),
                    }
                sentence_idx[0] += 1
            except Exception as e:
                logger.warning(f"[TTS] tail 合成失败，降级: {e}")
                yield {
                    "event": "tts_fallback",
                    "data": json.dumps({"type": "tts_fallback", "text": tail}),
                }
        else:
            yield {
                "event": "tts_fallback",
                "data": json.dumps({"type": "tts_fallback", "text": tail}),
            }

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
                full_response = ""
                first_token = True
                async for content in mediator.chat_engine.stream_chat_with_messages(
                    request.message,
                    request.messages,
                    request.model,
                    request.conversation_id,
                    request.user_id,
                    request.provider_id,
                ):
                    if first_token:
                        logger.info(
                            f"[SSE] 首个数据到达, 耗时={(_time.time()-t_start)*1000:.0f}ms"
                        )
                        first_token = False
                    if content.startswith("{"):
                        try:
                            evt = json.loads(content)
                            evt_type = evt.get("type", "unknown")
                            sse_event = (
                                "tool" if evt_type.startswith("tool") else "token"
                            )
                            yield {"event": sse_event, "data": content}
                        except json.JSONDecodeError:
                            full_response += content
                            async for ev in push_token_events(content):
                                yield ev
                    else:
                        full_response += content
                        async for ev in push_token_events(content):
                            yield ev
            else:
                full_response = ""
                async for content in mediator.chat_engine.stream_chat(
                    request.message,
                    request.conversation_id,
                    request.model,
                    request.user_id,
                    request.provider_id,
                ):
                    if content.startswith("{"):
                        yield {"event": "tool", "data": content}
                    else:
                        full_response += content
                        async for ev in push_token_events(content):
                            yield ev

            # flush 残余
            async for ev in flush_tail_events():
                yield ev

            # audio_done
            if enable_tts:
                yield {
                    "event": "audio_done",
                    "data": json.dumps(
                        {
                            "type": "audio_done",
                            "sentences": sentence_idx[0],
                            "sample_rate": 24000,
                            "sample_width": 2,
                            "channels": 1,
                        }
                    ),
                }

            # done
            yield {
                "event": "done",
                "data": json.dumps(
                    {
                        "type": "done",
                        "content": full_response,
                        "conversation_id": (
                            mediator.chat_engine.current_conversation.conversation_id
                            if mediator.chat_engine.current_conversation
                            else None
                        ),
                    }
                ),
            }
        except Exception as e:
            logger.error(f"Stream chat error: {e}", exc_info=True)
            yield {
                "event": "error",
                "data": json.dumps({"type": "error", "content": str(e)})
            }
            return  # Stop streaming after error

    return EventSourceResponse(event_generator())