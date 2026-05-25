# jarvis/utils/logger.py
"""日志工具模块"""
import logging
import sys
from pathlib import Path
from typing import Optional
from jarvis.config import settings


class JarvisLogger:
    """贾维斯日志器"""

    _loggers: dict[str, logging.Logger] = {}
    _initialized: bool = False

    @classmethod
    def init_logger(cls, name: str) -> logging.Logger:
        """初始化指定名称的日志器"""
        if name in cls._loggers:
            return cls._loggers[name]

        logger = logging.getLogger(name)
        logger.setLevel(getattr(logging, settings.log_level.upper()))

        # 避免重复添加 handler
        if logger.handlers:
            cls._loggers[name] = logger
            return logger

        # 控制台 Handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.DEBUG)

        # 文件 Handler
        log_file = settings.logs_dir / f"{name}.log"
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)

        # 格式化
        formatter = logging.Formatter(settings.log_format)
        console_handler.setFormatter(formatter)
        file_handler.setFormatter(formatter)

        logger.addHandler(console_handler)
        logger.addHandler(file_handler)

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