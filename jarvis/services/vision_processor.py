# jarvis/services/vision_processor.py
"""视觉处理服务 - 摄像头帧分析"""
from typing import Optional
import numpy as np
from jarvis.services.ollama_client import ollama_client
from jarvis.utils.logger import get_logger

logger = get_logger(__name__)


class VisionProcessor:
    """视觉处理器 - 分析摄像头帧"""

    def __init__(self):
        self.ollama = ollama_client
        logger.info("VisionProcessor initialized")

    async def analyze_frame(self, frame_data: bytes, prompt: str = "描述这张图片") -> dict:
        """分析单帧图像"""
        try:
            analysis = await self.ollama.vision_analyze(frame_data, prompt)
            return {
                "success": True,
                "analysis": analysis,
                "frame_size": len(frame_data)
            }
        except Exception as e:
            logger.error(f"Frame analysis error: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def detect_faces(self, frame_data: bytes) -> list[dict]:
        """人脸检测（简化实现）"""
        # TODO: 集成人脸检测模型（如 face_recognition 库）
        logger.debug("Face detection called (simplified)")
        return []

    async def detect_objects(self, frame_data: bytes) -> list[dict]:
        """物体检测（简化实现）"""
        # TODO: 集成目标检测模型（如 YOLO）
        logger.debug("Object detection called (simplified)")
        return []

    async def detect_scene(self, frame_data: bytes) -> str:
        """场景检测"""
        try:
            result = await self.ollama.vision_analyze(
                frame_data,
                "简单描述这个场景是在室内还是室外，以及主要活动"
            )
            return result
        except Exception as e:
            logger.error(f"Scene detection error: {e}")
            return "未知场景"

    async def stream_analysis(self, frame_iterator) -> dict:
        """持续分析摄像头流"""
        frame_count = 0
        for frame_data in frame_iterator:
            frame_count += 1
            if frame_count % 30 == 0:  # 每 30 帧分析一次
                analysis = await self.analyze_frame(frame_data)
                yield {
                    "frame": frame_count,
                    "analysis": analysis
                }

    async def process_frame_base64(self, base64_data: str, prompt: str) -> dict:
        """处理 Base64 编码的图像"""
        try:
            import base64 as b64
            frame_data = b64.b64decode(base64_data)
            return await self.analyze_frame(frame_data, prompt)
        except Exception as e:
            logger.error(f"Base64 frame processing error: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def to_dict(self) -> dict:
        """导出状态"""
        # check_health() is async — use cached status instead of calling it directly
        return {
            "ollama_connected": self._cached_health,
        }

    def _cached_health(self) -> bool:
        """Sync accessor for cached health status. Call update_health() first."""
        return getattr(self, '_health_cache', False)

    async def update_health(self):
        """Update cached health status (call this from async context)."""
        try:
            self._health_cache = await self.ollama.check_health()
        except Exception:
            self._health_cache = False