# jarvis/core/hardware_bridge.py
"""硬件桥接模块 - 摄像头/麦克风等硬件抽象"""
from abc import ABC, abstractmethod
from typing import Optional, AsyncIterator
from dataclasses import dataclass, field
from enum import Enum
import asyncio

from jarvis.utils.logger import get_logger

logger = get_logger(__name__)


class HardwareType(str, Enum):
    """硬件类型"""
    CAMERA = "camera"
    MICROPHONE = "microphone"
    SCREEN = "screen"
    KEYBOARD = "keyboard"
    MOUSE = "mouse"


@dataclass
class HardwareStatus:
    """硬件状态"""
    hardware_type: HardwareType
    connected: bool = False
    device_id: Optional[int] = None
    info: dict = field(default_factory=dict)


class HardwareObserver(ABC):
    """硬件观察者（Observer Pattern）"""

    @abstractmethod
    def on_status_change(self, status: HardwareStatus):
        """状态变更通知"""
        pass


class CameraObserver(HardwareObserver):
    """摄像头观察者"""

    def on_status_change(self, status: HardwareStatus):
        if status.connected:
            logger.info(f"Camera {status.device_id} connected: {status.info}")
        else:
            logger.info(f"Camera {status.device_id} disconnected")


class VoiceLevelObserver(HardwareObserver):
    """音量级别观察者"""

    def on_status_change(self, status: HardwareStatus):
        if status.hardware_type == HardwareType.MICROPHONE:
            level = status.info.get("voice_level", 0)
            logger.debug(f"Voice level: {level:.2f}")


class HardwareMonitor:
    """硬件监控器（Subject）"""

    def __init__(self):
        self._observers: list[HardwareObserver] = []

    def attach(self, observer: HardwareObserver):
        """添加观察者"""
        self._observers.append(observer)

    def detach(self, observer: HardwareObserver):
        """移除观察者"""
        if observer in self._observers:
            self._observers.remove(observer)

    def notify(self, status: HardwareStatus):
        """通知所有观察者"""
        for observer in self._observers:
            try:
                observer.on_status_change(status)
            except Exception as e:
                logger.error(f"Observer notification error: {e}")


class HardwareBridge:
    """硬件桥接 - 统一管理摄像头、麦克风等硬件"""

    def __init__(self):
        self.monitor = HardwareMonitor()
        self._camera_stream: Optional[AsyncIterator[bytes]] = None
        self._camera_active = False
        self._setup_observers()
        logger.info("HardwareBridge initialized")

    def _setup_observers(self):
        """设置默认观察者"""
        self.monitor.attach(CameraObserver())
        self.monitor.attach(VoiceLevelObserver())

    async def start_camera(self, device_id: int = 0) -> str:
        """启动摄像头 - 返回 stream_id"""
        try:
            # 浏览器 WebRTC 通过 WebSocket 发送摄像头流
            # 这里记录状态，不直接访问摄像头（由前端处理）
            self._camera_active = True
            stream_id = f"camera_{device_id}"

            self.monitor.notify(HardwareStatus(
                hardware_type=HardwareType.CAMERA,
                connected=True,
                device_id=device_id,
                info={"stream_id": stream_id}
            ))

            logger.info(f"Camera stream started: {stream_id}")
            return stream_id
        except Exception as e:
            logger.error(f"Failed to start camera: {e}")
            raise

    async def stop_camera(self, stream_id: str):
        """停止摄像头"""
        self._camera_active = False
        device_id = int(stream_id.split("_")[1]) if "_" in stream_id else 0

        self.monitor.notify(HardwareStatus(
            hardware_type=HardwareType.CAMERA,
            connected=False,
            device_id=device_id
        ))
        logger.info(f"Camera stream stopped: {stream_id}")

    async def get_camera_frame(self, stream_id: str) -> Optional[bytes]:
        """获取单帧图像（实际由 WebSocket 传输）"""
        # 这里返回 None，实际帧数据由 WebSocket 从前端接收
        return None

    async def process_camera_stream(self, stream_id: str, frames: AsyncIterator[bytes]):
        """处理摄像头流"""
        self._camera_active = True
        async for frame in frames:
            if not self._camera_active:
                break
            yield frame

    async def start_microphone(self) -> str:
        """启动麦克风"""
        stream_id = "microphone_0"
        self.monitor.notify(HardwareStatus(
            hardware_type=HardwareType.MICROPHONE,
            connected=True,
            device_id=0,
            info={"stream_id": stream_id}
        ))
        logger.info("Microphone started")
        return stream_id

    async def stop_microphone(self):
        """停止麦克风"""
        self.monitor.notify(HardwareStatus(
            hardware_type=HardwareType.MICROPHONE,
            connected=False,
            device_id=0
        ))
        logger.info("Microphone stopped")

    def get_status(self) -> dict:
        """获取硬件状态"""
        return {
            "camera_active": self._camera_active,
            "observers_count": len(self.monitor._observers)
        }


# 全局单例
hardware_bridge = HardwareBridge()