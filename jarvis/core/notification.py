# jarvis/core/notification.py
"""通知模块 - 支持日志报错通知、WebSocket实时推送"""
import asyncio
import json
from datetime import datetime
from enum import Enum
from typing import Callable, Optional
from dataclasses import dataclass, asdict
from collections import defaultdict

from jarvis.utils.logger import get_logger

logger = get_logger(__name__)


class NotificationLevel(str, Enum):
    """通知级别"""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class NotificationType(str, Enum):
    """通知类型"""
    SYSTEM = "system"
    LOG_ERROR = "log_error"
    TASK_COMPLETE = "task_complete"
    TASK_FAILED = "task_failed"
    CHAT_MESSAGE = "chat_message"
    HARDWARE_STATUS = "hardware_status"
    MEMORY_ALERT = "memory_alert"


@dataclass
class Notification:
    """通知数据模型"""
    id: str
    level: NotificationLevel
    type: NotificationType
    title: str
    message: str
    timestamp: str
    metadata: Optional[dict] = None

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


class NotificationHandler:
    """通知处理器接口"""

    async def send(self, notification: Notification):
        """发送通知"""
        raise NotImplementedError


class NotificationManager:
    """通知管理器 - 核心组件"""

    def __init__(self):
        self._handlers: list[NotificationHandler] = []
        self._subscribers: dict[str, list[Callable]] = defaultdict(list)
        self._history: list[Notification] = []
        self._max_history = 100
        logger.info("NotificationManager initialized")

    def subscribe(self, event_type: str, callback: Callable):
        """订阅通知"""
        self._subscribers[event_type].append(callback)
        logger.debug(f"Subscribed to {event_type}: {callback}")

    def unsubscribe(self, event_type: str, callback: Callable):
        """取消订阅"""
        if event_type in self._subscribers:
            self._subscribers[event_type].remove(callback)

    async def notify(self, notification: Notification):
        """发送通知到所有处理器和订阅者"""
        # 保存历史
        self._history.append(notification)
        if len(self._history) > self._max_history:
            self._history.pop(0)

        # 调用订阅者
        for callback in self._subscribers.get(notification.type.value, []):
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(notification)
                else:
                    callback(notification)
            except Exception as e:
                logger.error(f"Notification callback error: {e}")

        # 调用处理器
        for handler in self._handlers:
            try:
                await handler.send(notification)
            except Exception as e:
                logger.error(f"Notification handler error: {e}")

    def send_notification(
        self,
        level: NotificationLevel,
        notification_type: NotificationType,
        title: str,
        message: str,
        metadata: Optional[dict] = None
    ) -> Notification:
        """同步发送通知（创建后立即发送）"""
        notification = Notification(
            id=self._generate_id(),
            level=level,
            type=notification_type,
            title=title,
            message=message,
            timestamp=datetime.now().isoformat(),
            metadata=metadata
        )
        asyncio.create_task(self.notify(notification))
        return notification

    def error(self, title: str, message: str, metadata: Optional[dict] = None) -> Notification:
        """发送错误通知"""
        return self.send_notification(
            NotificationLevel.ERROR,
            NotificationType.LOG_ERROR,
            title,
            message,
            metadata
        )

    def warning(self, title: str, message: str, metadata: Optional[dict] = None) -> Notification:
        """发送警告通知"""
        return self.send_notification(
            NotificationLevel.WARNING,
            NotificationType.SYSTEM,
            title,
            message,
            metadata
        )

    def info(self, title: str, message: str, metadata: Optional[dict] = None) -> Notification:
        """发送信息通知"""
        return self.send_notification(
            NotificationLevel.INFO,
            NotificationType.SYSTEM,
            title,
            message,
            metadata
        )

    def task_complete(self, task_id: str, result: str) -> Notification:
        """任务完成通知"""
        return self.send_notification(
            NotificationLevel.INFO,
            NotificationType.TASK_COMPLETE,
            "任务完成",
            result,
            {"task_id": task_id}
        )

    def task_failed(self, task_id: str, error: str) -> Notification:
        """任务失败通知"""
        return self.send_notification(
            NotificationLevel.ERROR,
            NotificationType.TASK_FAILED,
            "任务失败",
            error,
            {"task_id": task_id}
        )

    def get_history(self, limit: int = 50) -> list[dict]:
        """获取通知历史"""
        return [n.to_dict() for n in self._history[-limit:]]

    def clear_history(self):
        """清空通知历史"""
        self._history.clear()

    def _generate_id(self) -> str:
        """生成通知ID"""
        import uuid
        return str(uuid.uuid4())[:8]


class WebSocketNotifier(NotificationHandler):
    """WebSocket通知处理器"""

    def __init__(self):
        self._connections: set = set()
        logger.info("WebSocketNotifier initialized")

    def add_connection(self, websocket):
        """添加WebSocket连接"""
        self._connections.add(websocket)
        logger.debug(f"WebSocket added, total: {len(self._connections)}")

    def remove_connection(self, websocket):
        """移除WebSocket连接"""
        self._connections.discard(websocket)
        logger.debug(f"WebSocket removed, total: {len(self._connections)}")

    async def send(self, notification: Notification):
        """通过WebSocket发送通知"""
        if not self._connections:
            return

        message = json.dumps({
            "type": "notification",
            "data": notification.to_dict()
        })

        dead_connections = set()
        for ws in self._connections:
            try:
                await ws.send_text(message)
            except Exception as e:
                logger.warning(f"Failed to send to WebSocket: {e}")
                dead_connections.add(ws)

        # 清理断开的连接
        self._connections -= dead_connections


# 全局通知管理器
notification_manager = NotificationManager()
ws_notifier = WebSocketNotifier()
notification_manager._handlers.append(ws_notifier)