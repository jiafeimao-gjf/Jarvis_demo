# jarvis/api/voice.py
"""语音相关 API"""
from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel, Field
from typing import Optional

from jarvis.core.mediator import mediator
from jarvis.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/voice", tags=["voice"])


class VoiceRequest(BaseModel):
    """语音请求模型"""
    audioData: Optional[str] = Field(None, description="Base64 编码的音频")
    conversationId: Optional[str] = Field(None, description="当前对话 ID")

    class Config:
        populate_by_name = True


class VoiceResponse(BaseModel):
    """语音响应模型"""
    text: str = ""
    response: Optional[str] = None
    tts: Optional[dict] = None


@router.post("")
async def voice_chat(request: VoiceRequest):
    """语音输入 → 对话处理"""
    try:
        if not request.audioData:
            raise HTTPException(status_code=400, detail="No audio data")

        import base64
        audio_data = base64.b64decode(request.audioData)

        result = await mediator.process_voice(audio_data, request.conversationId)
        return VoiceResponse(
            text=result.get("text", ""),
            response=result.get("response", ""),
            tts=result.get("tts", {})
        )
    except Exception as e:
        logger.error(f"Voice error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/upload")
async def voice_upload(file: UploadFile = File(...)):
    """上传音频文件进行语音识别"""
    try:
        audio_data = await file.read()

        # 处理音频
        text = await mediator.voice_engine.process_voice_input(audio_data)

        if text:
            # 如果识别成功，进行对话处理
            result = await mediator.process_chat(text)
            return {
                "text": text,
                "response": result.get("response", ""),
                "tts": result.get("tts", {})
            }
        return {"text": "", "response": None, "tts": {}}
    except Exception as e:
        logger.error(f"Voice upload error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tts")
async def text_to_speech(text: str):
    """文字转语音"""
    try:
        result = await mediator.voice_engine.text_to_speech(text)
        return result
    except Exception as e:
        logger.error(f"TTS error: {e}")
        raise HTTPException(status_code=500, detail=str(e))