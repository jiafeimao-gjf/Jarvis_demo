# jarvis/main.py
"""FastAPI 应用入口"""
import sys
from pathlib import Path

# 添加项目根目录到 path
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from jarvis.config import settings, config_manager
from jarvis.api.routes import api_router
from jarvis.utils.logger import get_logger

logger = get_logger(__name__)

# 创建 FastAPI 应用
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="贾维斯智能助手系统",
    debug=settings.server.debug,
)

# 配置 CORS - 使用新的 CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors.allow_origins,
    allow_credentials=settings.cors.allow_credentials,
    allow_methods=settings.cors.allow_methods,
    allow_headers=settings.cors.allow_headers,
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
            "GET  /api/config - 系统配置",
            "PUT  /api/config - 更新配置",
        ]
    }


@app.get("/api/config")
async def get_config():
    """获取系统配置（隐藏敏感信息）"""
    return config_manager.to_dict()


@app.put("/api/config")
async def update_config(key: str, value):
    """更新配置项"""
    config_manager.update(key, value)
    return {"success": True, "key": key, "value": value}


# 通知 API
@app.get("/api/notifications")
async def get_notifications(limit: int = 50):
    """获取通知历史"""
    from jarvis.core.notification import notification_manager
    return {
        "notifications": notification_manager.get_history(limit),
        "count": len(notification_manager._history)
    }


@app.delete("/api/notifications")
async def clear_notifications():
    """清空通知历史"""
    from jarvis.core.notification import notification_manager
    notification_manager.clear_history()
    return {"success": True}


# WebSocket 端点
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """通用 WebSocket 端点"""
    await websocket.accept()
    logger.info("WebSocket connected")

    # 注册到 WebSocket 通知器
    from jarvis.core.notification import ws_notifier
    ws_notifier.add_connection(websocket)

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
            elif msg_type == "notifications":
                # 获取通知历史
                from jarvis.core.notification import notification_manager
                await websocket.send_json({
                    "type": "notifications",
                    "data": notification_manager.get_history()
                })

    except Exception as e:
        # 忽略正常的连接关闭错误 (1001, 1000, etc.)
        error_code = getattr(e, 'code', None)
        if error_code in (1001, 1000, None):
            pass  # Normal close
        else:
            logger.error(f"WebSocket error: {e}")
    finally:
        ws_notifier.remove_connection(websocket)
        try:
            await websocket.close()
        except Exception:
            # WebSocket already closed or closing
            pass


# 启动事件
@app.on_event("startup")
async def startup_event():
    """应用启动"""
    logger.info(f"{settings.app_name} v{settings.app_version} starting...")
    settings.storage.ensure_directories()
    logger.info("Directories initialized")
    # Pre-load provider instances from DB
    from jarvis.services.ai.instance_config import get_instance_store
    store = get_instance_store()
    await store.load()
    logger.info(f"Provider instances loaded: {[i.id for i in store.get_all()]}")

    # Pre-load skills (seed from disk if first run, then sync metadata to DB)
    from jarvis.services.skill_store import get_skill_store
    skill_store = get_skill_store()
    skills = await skill_store.load()
    logger.info(f"Skills loaded: {[s.id for s in skill_store.list_all()]}")

    # TTS / 声音克隆探测（不强制依赖）
    try:
        settings.voice_clone.refs_dir.mkdir(parents=True, exist_ok=True)
        settings.voice_clone.outputs_dir.mkdir(parents=True, exist_ok=True)
        from jarvis.services.tts import f5_tts, voice_ref_manager
        logger.info(
            f"[TTS] F5-TTS enabled={settings.voice_clone.enabled}, "
            f"available={f5_tts.available}, device={f5_tts.device}, "
            f"ref_exists={voice_ref_manager.has_active()}"
        )
        if f5_tts.last_error:
            logger.warning(f"[TTS] last error: {f5_tts.last_error}")
        # 后台预热 — 避免首次合成卡 10-60s (MPS kernel 编译 + 模型加载)
        if f5_tts.available:
            import asyncio as _aio
            _aio.create_task(f5_tts.prewarm())
    except Exception as e:
        logger.warning(f"[TTS] 初始化检查失败：{e}")


@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭"""
    logger.info("Shutting down...")
    from jarvis.services.ollama_client import ollama_client
    await ollama_client.close()
    from jarvis.core.mediator import mediator
    await mediator.chat_engine.router.close()
    logger.info("Shutdown complete")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "jarvis.main:app",
        host=config_manager.get("server.host"),
        port=config_manager.get("server.port"),
        reload=config_manager.get("server.reload"),
    )