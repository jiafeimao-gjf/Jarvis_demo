# tests/test_entities.py
"""测试领域实体"""
import pytest
from datetime import datetime
from jarvis.core.entities import Message, Conversation, Step


class TestMessage:
    """测试 Message 实体"""

    def test_create_message_with_defaults(self):
        """测试默认消息创建"""
        msg = Message()
        assert msg.role == "user"
        assert msg.content == ""
        assert msg.message_id is not None
        assert isinstance(msg.timestamp, datetime)

    def test_create_message_with_params(self):
        """测试带参数的消息创建"""
        msg = Message(role="assistant", content="Hello")
        assert msg.role == "assistant"
        assert msg.content == "Hello"

    def test_message_to_dict(self):
        """测试消息转换为字典"""
        msg = Message(role="user", content="Test message")
        data = msg.to_dict()
        assert data["role"] == "user"
        assert data["content"] == "Test message"
        assert "message_id" in data
        assert "timestamp" in data

    def test_message_to_dict_with_string_timestamp(self):
        """测试消息 timestamp 为字符串时的处理"""
        msg = Message(role="user", content="Test", timestamp="2024-01-01T00:00:00")
        data = msg.to_dict()
        assert data["timestamp"] == "2024-01-01T00:00:00"


class TestConversation:
    """测试 Conversation 实体"""

    def test_create_conversation_with_defaults(self):
        """测试默认对话创建"""
        conv = Conversation()
        assert conv.conversation_id is not None
        assert conv.user_id == ""
        assert conv.messages == []
        assert conv.context == {}

    def test_create_conversation_with_params(self):
        """测试带参数的对话创建"""
        conv = Conversation(user_id="test_user")
        assert conv.user_id == "test_user"

    def test_add_message(self):
        """测试添加消息"""
        conv = Conversation()
        msg = conv.add_message("user", "Hello")
        assert msg.role == "user"
        assert msg.content == "Hello"
        assert len(conv.messages) == 1

    def test_get_history(self):
        """测试获取历史消息"""
        conv = Conversation()
        conv.add_message("user", "Message 1")
        conv.add_message("assistant", "Message 2")
        conv.add_message("user", "Message 3")

        history = conv.get_history(limit=2)
        assert len(history) == 2
        assert history[0].content == "Message 2"
        assert history[1].content == "Message 3"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])