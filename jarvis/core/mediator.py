# jarvis/core/mediator.py
"""中介者模式 - 协调各引擎之间的通信"""
from typing import Optional, Any, Callable, Awaitable
from dataclasses import dataclass
from jarvis.core.entities import JarvisEvent, JarvisEventType
from jarvis.core.chat_engine import ChatEngine
from jarvis.core.voice_engine import VoiceEngine
from jarvis.core.task_engine import TaskEngine
from jarvis.core.hardware_bridge import hardware_bridge
from jarvis.core.memory_store import memory_store
from jarvis.services.vision_processor import VisionProcessor
from jarvis.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class JarvisEvent:
    """贾维斯事件"""
    event_id: str
    event_type: JarvisEventType
    payload: dict
    metadata: dict


class JarvisMediator:
    """中介者 - 统一协调各引擎之间的通信（Mediator Pattern）"""

    def __init__(self):
        self.chat_engine = ChatEngine()
        self.voice_engine = VoiceEngine()
        self.task_engine = TaskEngine()
        self.hardware_bridge = hardware_bridge
        self.memory_store = memory_store
        self.vision_processor = VisionProcessor()

        self._event_handlers: dict[str, Callable] = {}
        self._register_handlers()
        logger.info("JarvisMediator initialized")

    def _register_handlers(self):
        """注册事件处理器"""
        self._event_handlers = {
            "voice.input": self._handle_voice_input,
            "chat.message": self._handle_chat_message,
            "camera.frame": self._handle_camera_frame,
            "task.execute": self._handle_task_execution,
        }

    async def route_event(self, event: JarvisEvent) -> Any:
        """根据事件类型路由到对应处理器"""
        handler = self._event_handlers.get(event.event_type.value)
        if handler:
            try:
                return await handler(event)
            except Exception as e:
                logger.error(f"Event handler error: {e}")
                return {"error": str(e)}
        logger.warning(f"No handler for event type: {event.event_type}")
        return None

    async def _handle_voice_input(self, event: JarvisEvent) -> dict:
        """处理语音输入"""
        audio_data = event.payload.get("audio_data")
        if not audio_data:
            return {"error": "No audio data"}

        # 1. 语音转文字（简化实现）
        text = await self.voice_engine.process_voice_input(audio_data)

        # 2. 如果有语音识别结果，进行对话
        if text:
            response = await self.chat_engine.chat(text)
            # 3. TTS 播放
            tts_result = await self.voice_engine.text_to_speech(response)
            return {
                "text": text,
                "response": response,
                "tts": tts_result
            }
        return {"text": "", "response": None}

    async def _handle_chat_message(self, event: JarvisEvent) -> dict:
        """处理文字对话"""
        text = event.payload.get("text")
        conversation_id = event.payload.get("conversation_id")

        if not text:
            return {"error": "No text provided"}

        response = await self.chat_engine.chat(text, conversation_id)
        return {
            "text": text,
            "response": response,
            "conversation_id": self.chat_engine.current_conversation.conversation_id
            if self.chat_engine.current_conversation else None
        }

    async def _handle_camera_frame(self, event: JarvisEvent) -> dict:
        """处理摄像头帧"""
        frame_data = event.payload.get("frame_data")
        prompt = event.payload.get("prompt", "描述这张图片")

        if not frame_data:
            return {"error": "No frame data"}

        result = await self.vision_processor.analyze_frame(frame_data, prompt)
        return result

    async def _handle_task_execution(self, event: JarvisEvent) -> dict:
        """处理任务执行"""
        task_description = event.payload.get("task")
        if not task_description:
            return {"error": "No task description"}

        task = await self.task_engine.execute_task(task_description)
        return {
            "task_id": task.task_id,
            "status": task.status.value,
            "result": task.result
        }

    async def process_chat(self, text: str, conversation_id: Optional[str] = None) -> dict:
        """便捷方法：处理对话"""
        event = JarvisEvent(
            event_id="",
            event_type=JarvisEventType.CHAT_MESSAGE,
            payload={"text": text, "conversation_id": conversation_id},
            metadata={}
        )
        return await self._handle_chat_message(event)

    async def process_voice(self, audio_data: bytes) -> dict:
        """便捷方法：处理语音"""
        event = JarvisEvent(
            event_id="",
            event_type=JarvisEventType.VOICE_INPUT,
            payload={"audio_data": audio_data},
            metadata={}
        )
        return await self._handle_voice_input(event)

    async def process_camera(self, frame_data: bytes, prompt: str = "描述这张图片") -> dict:
        """便捷方法：处理摄像头帧"""
        event = JarvisEvent(
            event_id="",
            event_type=JarvisEventType.CAMERA_FRAME,
            payload={"frame_data": frame_data, "prompt": prompt},
            metadata={}
        )
        return await self._handle_camera_frame(event)

    def get_status(self) -> dict:
        """获取系统状态"""
        return {
            "chat_engine": self.chat_engine.to_dict(),
            "voice_engine": self.voice_engine.to_dict(),
            "task_engine": self.task_engine.to_dict(),
            "hardware_bridge": self.hardware_bridge.get_status(),
        }


# 全局单例
mediator = JarvisMediator()