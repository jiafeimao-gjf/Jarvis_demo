# jarvis/config.py
"""系统配置管理"""
import os
from pathlib import Path
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """贾维斯系统配置"""

    # 应用配置
    app_name: str = "JARVIS"
    app_version: str = "0.1.0"
    debug: bool = True

    # 服务器配置
    host: str = "0.0.0.0"
    port: int = 9529

    # 路径配置
    base_dir: Path = Path(__file__).parent.parent
    memory_dir: Path = base_dir / "memory"
    logs_dir: Path = base_dir / "logs"

    # 数据库配置
    sqlite_db_path: Path = memory_dir / "jarvis.db"
    lance_db_path: Path = memory_dir / "lance_db"

    # Ollama配置
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:4b"
    ollama_vision_model: str = "qwen3-vl:4b"
    ollama_t2i_model: str = "x/z-image-turbo"

    # 硬件配置
    camera_device_id: int = 0
    camera_width: int = 640
    camera_height: int = 480
    camera_fps: int = 30

    # 音频配置
    sample_rate: int = 16000
    channels: int = 1
    chunk_size: int = 1024

    # TTS配置
    tts_provider: str = "browser"  # browser | qwen3-tts

    # 日志配置
    log_level: str = "INFO"
    log_format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


# 全局单例
settings = Settings()


def ensure_directories():
    """确保必要的目录存在"""
    settings.memory_dir.mkdir(parents=True, exist_ok=True)
    settings.lance_db_path.mkdir(parents=True, exist_ok=True)
    settings.logs_dir.mkdir(parents=True, exist_ok=True)


ensure_directories()