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
    image: Optional[str] = None
    thinking: Optional[str] = None  # Model reasoning/thinking
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "message_id": self.message_id,
            "role": self.role,
            "content": self.content,
            "image": self.image,
            "thinking": self.thinking,
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
    topic: Optional[str] = None
    messages: list[Message] = field(default_factory=list)
    context: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    # ── v3 新增: subagent 子会话支持 ──
    parent_conversation_id: Optional[str] = None  # 父会话 (None = 主会话)
    session_kind: str = "main"                     # "main" | "subagent"
    subagent_role: Optional[str] = None           # researcher / coder / ...
    subagent_task: Optional[str] = None            # 触发时的任务描述
    triggered_by_message_id: Optional[str] = None  # 主会话里哪条消息触发的
    metadata: dict = field(default_factory=dict)   # 自由扩展 (mode, batch_size, ...)

    def set_topic(self, topic: str) -> None:
        """设置对话主题（自动 trim + 限长 60 字符）"""
        if topic is None:
            self.topic = None
        else:
            self.topic = topic.strip()[:60] or None
        self.updated_at = datetime.now()

    def add_message(self, role: str, content: str, image: str = None, thinking: str = None) -> Message:
        """添加消息"""
        msg = Message(role=role, content=content, image=image, thinking=thinking)
        self.messages.append(msg)
        self.updated_at = datetime.now()
        return msg

    def get_history(self, limit: int = 10) -> list[Message]:
        """获取历史消息"""
        return self.messages[-limit:]

    def is_subagent(self) -> bool:
        """是否子会话."""
        return self.session_kind == "subagent"

    def to_dict(self) -> dict:
        """完整字典化 (含 subagent 字段, 用于持久化)."""
        return {
            "conversation_id": self.conversation_id,
            "user_id": self.user_id,
            "topic": self.topic,
            "messages": [m.to_dict() for m in self.messages],
            "context": self.context,
            "parent_conversation_id": self.parent_conversation_id,
            "session_kind": self.session_kind,
            "subagent_role": self.subagent_role,
            "subagent_task": self.subagent_task,
            "triggered_by_message_id": self.triggered_by_message_id,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat() if isinstance(self.created_at, datetime) else self.created_at,
            "updated_at": self.updated_at.isoformat() if isinstance(self.updated_at, datetime) else self.updated_at,
        }


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