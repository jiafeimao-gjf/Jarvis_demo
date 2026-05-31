# jarvis/api/camera.py
"""摄像头相关 API"""
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from typing import Optional
import json
import base64

from jarvis.core.mediator import mediator
from jarvis.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/camera", tags=["camera"])


class CameraFrameRequest(BaseModel):
    """摄像头帧请求模型"""
    frame_data: str  # Base64 编码
    prompt: Optional[str] = "描述这张图片"


class CameraResponse(BaseModel):
    """摄像头响应模型"""
    success: bool
    analysis: Optional[str] = None
    error: Optional[str] = None


@router.post("/analyze")
async def analyze_frame(request: CameraFrameRequest):
    """分析单帧图像"""
    import time
    t0 = time.time()
    try:
        frame_bytes = base64.b64decode(request.frame_data)
        logger.info(
            f"[/camera/analyze] received frame: {len(frame_bytes)} bytes, "
            f"base64: {len(request.frame_data)} chars, prompt: {request.prompt[:50]}"
        )
        result = await mediator.process_camera(frame_bytes, request.prompt)
        elapsed = (time.time() - t0) * 1000
        logger.info(
            f"[/camera/analyze] done in {elapsed:.0f}ms, "
            f"success={result.get('success')}, analysis_len={len(result.get('analysis') or '')}"
        )
        return CameraResponse(
            success=result.get("success", False),
            analysis=result.get("analysis"),
            error=result.get("error")
        )
    except Exception as e:
        elapsed = (time.time() - t0) * 1000
        logger.error(f"[/camera/analyze] error after {elapsed:.0f}ms: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/start")
async def start_camera(device_id: int = 0):
    """启动摄像头流"""
    try:
        stream_id = await mediator.hardware_bridge.start_camera(device_id)
        return {"stream_id": stream_id, "status": "started"}
    except Exception as e:
        logger.error(f"Start camera error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stop")
async def stop_camera(stream_id: str):
    """停止摄像头流"""
    try:
        await mediator.hardware_bridge.stop_camera(stream_id)
        return {"stream_id": stream_id, "status": "stopped"}
    except Exception as e:
        logger.error(f"Stop camera error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.websocket("/ws")
async def camera_websocket(websocket: WebSocket):
    """摄像头 WebSocket 流处理"""
    await websocket.accept()
    logger.info("Camera WebSocket connected")

    try:
        while True:
            # 接收消息
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type == "frame":
                # 处理帧数据
                frame_base64 = data.get("data")
                prompt = data.get("prompt", "描述这张图片")

                try:
                    frame_bytes = base64.b64decode(frame_base64)
                    result = await mediator.process_camera(frame_bytes, prompt)

                    await websocket.send_json({
                        "type": "analysis",
                        "result": result
                    })
                except Exception as e:
                    await websocket.send_json({
                        "type": "error",
                        "message": str(e)
                    })

            elif msg_type == "start":
                device_id = data.get("device_id", 0)
                stream_id = await mediator.hardware_bridge.start_camera(device_id)
                await websocket.send_json({
                    "type": "started",
                    "stream_id": stream_id
                })

            elif msg_type == "stop":
                stream_id = data.get("stream_id")
                await mediator.hardware_bridge.stop_camera(stream_id)
                await websocket.send_json({
                    "type": "stopped",
                    "stream_id": stream_id
                })

    except WebSocketDisconnect:
        logger.info("Camera WebSocket disconnected")
    except Exception as e:
        logger.error(f"Camera WebSocket error: {e}")
        await websocket.send_json({
            "type": "error",
            "message": str(e)
        })