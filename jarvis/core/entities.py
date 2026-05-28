# jarvis/core/entities.py
"""领域实体定义"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Any
import uuid


class TaskStatus(str, Enum):
    """任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class JarvisEventType(str, Enum):
    """贾维斯事件类型"""
    VOICE_INPUT = "voice.input"
    VOICE_OUTPUT = "voice.output"
    CAMERA_FRAME = "camera.frame"
    CHAT_MESSAGE = "chat.message"
    TASK_EXECUTED = "task.executed"
    HARDWARE_CONNECTED = "hardware.connected"
    HARDWARE_DISCONNECTED = "hardware.disconnected"


@dataclass
class JarvisEvent:
    """贾维斯事件基类"""
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=datetime.now)
    event_type: JarvisEventType = JarvisEventType.CHAT_MESSAGE
    payload: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp.isoformat(),
            "event_type": self.event_type.value,
            "payload": self.payload,
            "metadata": self.metadata
        }


@dataclass
class Message:
    """对话消息"""
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    role: str = "user"  # user | assistant | system
    content: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "message_id": self.message_id,
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat() if isinstance(self.timestamp, datetime) else self.timestamp,
            "metadata": self.metadata
        }


@dataclass
class User:
    """用户实体"""
    user_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = "User"
    preferences: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class Conversation:
    """对话上下文"""
    conversation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str = ""
    messages: list[Message] = field(default_factory=list)
    context: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def add_message(self, role: str, content: str) -> Message:
        """添加消息"""
        msg = Message(role=role, content=content)
        self.messages.append(msg)
        self.updated_at = datetime.now()
        return msg

    def get_history(self, limit: int = 10) -> list[Message]:
        """获取历史消息"""
        return self.messages[-limit:]


@dataclass
class Step:
    """任务步骤"""
    step_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    tool: str = ""
    params: dict = field(default_factory=dict)
    result: Optional[Any] = None
    status: TaskStatus = TaskStatus.PENDING


@dataclass
class Task:
    """任务实体"""
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    description: str = ""
    steps: list[Step] = field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class Memory:
    """记忆实体"""
    memory_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    key: str = ""
    content: str = ""
    vector: list[float] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)