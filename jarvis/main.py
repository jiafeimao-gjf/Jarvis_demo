# jarvis/main.py
"""FastAPI 应用入口"""
import sys
from pathlib import Path

# 添加项目根目录到 path
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from jarvis.config import settings
from jarvis.api.routes import api_router
from jarvis.utils.logger import get_logger

logger = get_logger(__name__)

# 创建 FastAPI 应用
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="贾维斯智能助手系统",
    debug=settings.debug,
)

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8529", "http://127.0.0.1:8529"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册 API 路由
app.include_router(api_router)


@app.get("/")
async def root():
    """根路径"""
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "status": "online"
    }


@app.get("/api")
async def api_info():
    """API 信息"""
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "endpoints": [
            "GET  /api/status - 系统状态",
            "GET  /api/health - 健康检查",
            "POST /api/chat - 文字对话",
            "POST /api/chat/stream - 流式对话",
            "POST /api/voice - 语音对话",
            "POST /api/camera/analyze - 图像分析",
            "WS   /api/camera/ws - 摄像头流",
            "GET  /api/memory - 记忆检索",
            "POST /api/memory - 保存记忆",
            "POST /api/execute - 任务执行",
        ]
    }


# WebSocket 端点
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """通用 WebSocket 端点"""
    await websocket.accept()
    logger.info("WebSocket connected")

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
            elif msg_type == "status":
                from jarvis.core.mediator import mediator
                await websocket.send_json({
                    "type": "status",
                    "data": mediator.get_status()
                })

    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        await websocket.close()


# 启动事件
@app.on_event("startup")
async def startup_event():
    """应用启动"""
    logger.info(f"{settings.app_name} v{settings.app_version} starting...")
    settings.memory_dir.mkdir(parents=True, exist_ok=True)
    settings.lance_db_path.mkdir(parents=True, exist_ok=True)
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Directories initialized")


@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭"""
    logger.info("Shutting down...")
    from jarvis.services.ollama_client import ollama_client
    await ollama_client.close()
    logger.info("Shutdown complete")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "jarvis.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )