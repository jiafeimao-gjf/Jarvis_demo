# jarvis/api/voice_tts.py
"""声音克隆相关 API — 参考音频管理 + 同步 TTS 合成。"""
import time
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from jarvis.config import settings
from jarvis.services.tts import (
    F5TTSUnavailable,
    browser_tts_payload,
    f5_tts,
    voice_clone_url_payload,
    voice_ref_manager,
)
from jarvis.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/voice", tags=["voice-clone"])


# =============== 参考音频管理 ===============

@router.post("/ref/upload")
async def upload_ref_audio(file: UploadFile = File(...)):
    """上传参考音频（multipart/form-data）。

    旧文件归档到 refs/history/，新文件覆盖 active (refs/voice.wav)。
    """
    try:
        return await voice_ref_manager.upload(file)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"上传 ref 失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ref/info")
async def get_ref_info():
    """获取当前 ref 信息 + TTS 可用性。"""
    info = voice_ref_manager.get_active_info()
    info["tts_available"] = f5_tts.available
    return info


@router.get("/ref/audio")
async def get_ref_audio():
    """下载当前 active 参考音频（前端试听用）。"""
    if not voice_ref_manager.has_active():
        raise HTTPException(status_code=404, detail="尚未上传参考音频")
    return FileResponse(
        voice_ref_manager.active_path,
        media_type="audio/wav",
        filename=voice_ref_manager.active_path.name,
    )


@router.put("/ref/text")
async def set_ref_text(body: dict):
    """设置参考文本（F5-TTS 必填，必须一字不差匹配 ref 音频）。"""
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="ref_text 不能为空")
    try:
        return voice_ref_manager.set_ref_text(text)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/ref")
async def delete_ref():
    """删除 active 参考音频 + 文本。"""
    return voice_ref_manager.delete_active()


@router.get("/ref/history")
async def get_ref_history():
    """历史归档列表。"""
    return {"items": voice_ref_manager.list_history()}


# =============== 同步 TTS ===============

@router.post("/synthesize")
async def synthesize(body: dict):
    """同步合成（整段 → wav URL）。

    返回两种形态（前端按 type 路由）:
      - {type: "voice_clone", audio_url, duration, text} 成功
      - {type: "browser_tts", text}                       降级
    """
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text 不能为空")
    speed = float(body.get("speed", settings.voice_clone.speed))

    if not f5_tts.available:
        logger.debug("[TTS] unavailable, fallback to browser")
        return browser_tts_payload(text)

    try:
        output_name = f"clone_{int(time.time() * 1000)}.wav"
        result = f5_tts.synthesize_to_wav(text, output_name=output_name, speed=speed)
        return voice_clone_url_payload(
            audio_url=result["output_url"],
            duration=result["duration"],
            text=text,
        )
    except F5TTSUnavailable as e:
        logger.warning(f"[TTS] synthesize 不可用，降级：{e}")
        return browser_tts_payload(text)
    except Exception as e:
        logger.error(f"[TTS] synthesize 失败: {e}", exc_info=True)
        return browser_tts_payload(text)


@router.get("/audio/{filename}")
async def serve_audio(filename: str):
    """静态服务 wav 输出（F5-TTS 合成结果）。

    同时兼容 voice-clone-demo 写到 ../voice-clone-demo/web/outputs/ 的旧路径。
    """
    # 防 path traversal
    safe = Path(filename).name
    if safe != filename or ".." in filename:
        raise HTTPException(status_code=400, detail="非法文件名")

    # 优先 jarvis 自己的 outputs_dir
    target = settings.voice_clone.outputs_dir / safe
    if not target.exists():
        # 兼容 demo 写到 ../voice-clone-demo/web/outputs/ 的情况
        demo_out = (
            Path(settings.storage.base_dir).parent
            / "voice-clone-demo"
            / "web"
            / "outputs"
            / safe
        )
        if demo_out.exists():
            target = demo_out

    if not target.exists():
        raise HTTPException(status_code=404, detail=f"音频文件不存在: {safe}")
    return FileResponse(target, media_type="audio/wav", filename=safe)


# =============== TTS 状态 ===============

@router.get("/status")
async def tts_status():
    """TTS 子系统状态。"""
    return {
        "enabled": settings.voice_clone.enabled,
        "ref_exists": voice_ref_manager.has_active(),
        "ref_info": voice_ref_manager.get_active_info(),
        "device": f5_tts.device,
        "available": f5_tts.available,
        "model_name": settings.voice_clone.model_name,
        "last_error": f5_tts.last_error,
    }