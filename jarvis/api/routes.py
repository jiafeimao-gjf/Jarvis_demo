# jarvis/api/routes.py
"""API路由定义"""
from fastapi import APIRouter
from jarvis.core.mediator import mediator
from jarvis.utils.logger import get_logger

logger = get_logger(__name__)

api_router = APIRouter(prefix="/api")


@api_router.get("/status")
async def get_status():
    """获取系统状态"""
    return {
        "status": "online",
        "version": "0.1.0",
        "systems": mediator.get_status()
    }


@api_router.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "healthy"}


# 注册子路由
from jarvis.api.chat import router as chat_router
from jarvis.api.voice import router as voice_router
from jarvis.api.memory import router as memory_router
from jarvis.api.execute import router as execute_router
from jarvis.api.camera import router as camera_router
from jarvis.api.providers import router as providers_router
from jarvis.api.voice_tts import router as voice_tts_router
from jarvis.api.skills import router as skills_router
from jarvis.api.logs import router as logs_router

api_router.include_router(chat_router)
api_router.include_router(voice_router)
api_router.include_router(memory_router)
api_router.include_router(execute_router)
api_router.include_router(camera_router)
api_router.include_router(providers_router)
api_router.include_router(voice_tts_router)
api_router.include_router(skills_router)
api_router.include_router(logs_router)