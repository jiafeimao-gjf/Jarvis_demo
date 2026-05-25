# jarvis/utils/logger.py
"""日志工具模块"""
import logging
import sys
from pathlib import Path
from typing import Optional


class NotificationLogHandler(logging.Handler):
    """日志通知处理器 - 将错误日志发送到通知系统"""

    def __init__(self):
        super().__init__()
        self._notification_manager = None

    def _get_notification_manager(self):
        if self._notification_manager is None:
            try:
                from jarvis.core.notification import notification_manager
                self._notification_manager = notification_manager
            except Exception:
                return None
        return self._notification_manager

    def emit(self, record: logging.LogRecord):
        """发送日志通知"""
        if record.levelno < logging.ERROR:
            return

        nm = self._get_notification_manager()
        if not nm:
            return

        try:
            from jarvis.core.notification import NotificationLevel, NotificationType
            nm.send_notification(
                level=NotificationLevel.ERROR if record.levelno == logging.ERROR else NotificationLevel.CRITICAL,
                notification_type=NotificationType.LOG_ERROR,
                title=f"日志错误: {record.name}",
                message=record.getMessage(),
                metadata={
                    "logger": record.name,
                    "level": record.levelname,
                    "file": record.filename,
                    "line": record.lineno
                }
            )
        except Exception:
            pass  # 避免通知系统故障影响日志


class JarvisLogger:
    """贾维斯日志器"""

    _loggers: dict[str, logging.Logger] = {}
    _initialized: bool = False
    _settings = None
    _notification_handler_added: bool = False

    @classmethod
    def _get_settings(cls):
        """延迟导入 settings 避免循环"""
        if cls._settings is None:
            from jarvis.config import settings
            cls._settings = settings
        return cls._settings

    @classmethod
    def init_logger(cls, name: str) -> logging.Logger:
        """初始化指定名称的日志器"""
        if name in cls._loggers:
            return cls._loggers[name]

        logger = logging.getLogger(name)
        s = cls._get_settings()
        log_level = getattr(logging, s.log_level.upper()) if s else logging.INFO

        # 处理嵌套配置
        if s:
            try:
                logs_dir = s.storage.logs_dir if hasattr(s, 'storage') and s.storage else None
            except Exception:
                logs_dir = None
        else:
            logs_dir = None

        logger.setLevel(log_level)

        # 避免重复添加 handler
        if logger.handlers:
            cls._loggers[name] = logger
            return logger

        # 控制台 Handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.DEBUG)

        # 文件 Handler
        if logs_dir:
            log_file = logs_dir / f"{name}.log"
            file_handler = logging.FileHandler(log_file, encoding="utf-8")
            file_handler.setLevel(logging.DEBUG)
        else:
            file_handler = None

        # 格式化
        formatter = logging.Formatter(
            s.log_format if s and hasattr(s, 'log_format') else "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        console_handler.setFormatter(formatter)

        logger.addHandler(console_handler)
        if file_handler:
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)

        # 添加日志通知处理器（只添加一次）
        if not cls._notification_handler_added:
            notification_handler = NotificationLogHandler()
            notification_handler.setLevel(logging.ERROR)
            logger.addHandler(notification_handler)
            cls._notification_handler_added = True

        cls._loggers[name] = logger
        return logger

    @classmethod
    def get_logger(cls, name: str) -> logging.Logger:
        """获取日志器"""
        if name not in cls._loggers:
            return cls.init_logger(name)
        return cls._loggers[name]


def get_logger(name: str) -> logging.Logger:
    """便捷获取日志器函数"""
    return JarvisLogger.get_logger(name)