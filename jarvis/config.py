# jarvis/config.py
"""系统配置管理 - 统一配置模块"""
import os
from pathlib import Path
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# ============== Provider Configurations ==============

class OllamaConfig(BaseModel):
    """Ollama 配置"""
    base_url: str = "http://localhost:11434"
    model: str = "qwen3:4b"
    vision_model: str = "qwen3-vl:4b"
    stt_model: str = "sendmeaiohyeah/whisper-large-v2"
    t2i_model: str = "x/z-image-turbo"
    timeout: float = 60.0
    max_retries: int = 3


class OpenAIConfig(BaseModel):
    """OpenAI 配置"""
    api_key: Optional[str] = None
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    timeout: float = 60.0


class AnthropicConfig(BaseModel):
    """Anthropic 配置"""
    api_key: Optional[str] = None
    base_url: str = "https://api.anthropic.com/v1"
    model: str = "claude-3-haiku-20240307"
    timeout: float = 60.0


class MiniMaxConfig(BaseModel):
    """MiniMax 配置"""
    api_key: Optional[str] = None
    base_url: str = "https://api.minimaxi.com/anthropic/v1"
    model: str = "MiniMax-M2.7"
    timeout: float = 60.0


# ============== AI Configuration ==============

class AIConfig(BaseModel):
    """AI 配置"""
    default_provider: str = "ollama"
    default_model: str = "qwen3:4b"
    enable_fallback: bool = True
    fallback_chain: List[str] = ["ollama", "openai", "anthropic", "minimax"]

    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    openai: OpenAIConfig = Field(default_factory=OpenAIConfig)
    anthropic: AnthropicConfig = Field(default_factory=AnthropicConfig)
    minimax: MiniMaxConfig = Field(default_factory=MiniMaxConfig)

    def get_provider_config(self, provider: str) -> Dict[str, Any]:
        """获取 provider 配置字典"""
        return getattr(self, provider.lower(), {}).model_dump() or {}


# ============== Hardware Configuration ==============

class HardwareConfig(BaseModel):
    """硬件配置"""
    camera_device_id: int = 0
    camera_width: int = 640
    camera_height: int = 480
    camera_fps: int = 30
    microphone_sample_rate: int = 16000
    audio_channels: int = 1


# ============== Storage Configuration ==============

class StorageConfig(BaseModel):
    """存储配置"""
    base_dir: Path = Path(__file__).parent.parent
    memory_dir: Path = Path(__file__).parent.parent / "memory"
    logs_dir: Path = Path(__file__).parent.parent / "logs"
    sqlite_db_path: Path = Path(__file__).parent.parent / "memory" / "jarvis.db"
    lance_db_path: Path = Path(__file__).parent.parent / "memory" / "lance_db"

    def ensure_directories(self):
        """确保必要的目录存在"""
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.lance_db_path.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)


# ============== Server Configuration ==============

class ServerConfig(BaseModel):
    """服务器配置"""
    host: str = "0.0.0.0"
    port: int = 9529
    debug: bool = False
    reload: bool = False


# ============== CORS Configuration ==============

class CORSConfig(BaseModel):
    """CORS 配置"""
    allow_origins: List[str] = ["http://localhost:8529", "http://127.0.0.1:8529"]
    allow_credentials: bool = True
    allow_methods: List[str] = ["*"]
    allow_headers: List[str] = ["*"]


# ============== Main Settings ==============

class Settings(BaseSettings):
    """贾维斯系统配置"""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        case_sensitive=False
    )

    # 基本信息
    app_name: str = "JARVIS"
    app_version: str = "0.1.0"

    # 子配置
    server: ServerConfig = Field(default_factory=ServerConfig)
    cors: CORSConfig = Field(default_factory=CORSConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    hardware: HardwareConfig = Field(default_factory=HardwareConfig)
    ai: AIConfig = Field(default_factory=AIConfig)

    # 日志
    log_level: str = "INFO"
    log_format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.storage.ensure_directories()

    def to_dict(self) -> Dict[str, Any]:
        """导出配置为字典（隐藏敏感信息）"""
        result = {
            "app_name": self.app_name,
            "app_version": self.app_version,
            "server": self.server.model_dump(),
            "ai": {
                "default_provider": self.ai.default_provider,
                "default_model": self.ai.default_model,
                "enable_fallback": self.ai.enable_fallback,
                "fallback_chain": self.ai.fallback_chain,
                "providers": {
                    "ollama": {
                        "base_url": self.ai.ollama.base_url,
                        "model": self.ai.ollama.model,
                        "vision_model": self.ai.ollama.vision_model,
                    },
                    "openai": {
                        "has_api_key": bool(self.ai.openai.api_key),
                    },
                    "anthropic": {
                        "has_api_key": bool(self.ai.anthropic.api_key),
                    },
                    "minimax": {
                        "has_api_key": bool(self.ai.minimax.api_key),
                    }
                }
            },
            "hardware": self.hardware.model_dump(),
            "storage": {
                "memory_dir": str(self.storage.memory_dir),
                "logs_dir": str(self.storage.logs_dir),
            },
            "log_level": self.log_level,
        }
        return result


# ============== Runtime Config Manager ==============

class ConfigManager:
    """运行时配置管理器，支持热更新"""

    _instance: Optional["ConfigManager"] = None
    _config: Settings

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._config = Settings()
        return cls._instance

    @property
    def settings(self) -> Settings:
        return self._config

    def update(self, key: str, value: Any):
        """更新配置项（支持嵌套 key: "ai.default_provider")"""
        keys = key.split(".")
        obj = self._config
        for k in keys[:-1]:
            obj = getattr(obj, k)
        setattr(obj, keys[-1], value)
        print(f"Config updated: {key} = {value}")

    def get(self, key: str) -> Any:
        """获取配置项"""
        keys = key.split(".")
        obj = self._config
        for k in keys:
            obj = getattr(obj, k)
        return obj

    def reload(self):
        """重新加载配置"""
        self._config = Settings()
        print("Configuration reloaded")

    def to_dict(self) -> Dict[str, Any]:
        """导出当前配置"""
        return self._config.to_dict()


# 全局单例
settings = Settings()
config_manager = ConfigManager()