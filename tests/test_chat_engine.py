# tests/test_chat_engine.py
"""测试对话引擎"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass
from jarvis.core.chat_engine import ChatEngine, SystemPromptSettings, MAX_TOOL_ITERATIONS


class TestChatEngineInit:
    """测试 ChatEngine 初始化"""

    def test_init_creates_engine(self):
        """测试引擎初始化"""
        with patch('jarvis.core.chat_engine.memory_store'):
            engine = ChatEngine()
            assert engine is not None
            assert engine.work_folder is not None

    def test_init_sets_providers(self):
        """测试 provider 注册"""
        with patch('jarvis.core.chat_engine.memory_store'):
            engine = ChatEngine()
            assert engine.router is not None
            assert engine.ai_config is not None


class TestSystemPromptSettings:
    """测试 SystemPromptSettings dataclass"""

    def test_default_values(self):
        """测试默认值"""
        settings = SystemPromptSettings()
        assert settings.persona == ""
        assert settings.abilities == ""
        assert settings.memory == ""
        assert settings.tools == ""
        assert settings.work_folder == ""

    def test_custom_values(self):
        """测试自定义值"""
        settings = SystemPromptSettings(
            persona="You are a helpful assistant",
            abilities="Can help with coding",
            memory="Remembers context",
            tools="File, bash, browser",
            work_folder="/home/user"
        )
        assert settings.persona == "You are a helpful assistant"
        assert settings.abilities == "Can help with coding"
        assert settings.memory == "Remembers context"
        assert settings.tools == "File, bash, browser"
        assert settings.work_folder == "/home/user"


class TestBuildSystemPrompt:
    """测试构建系统提示词"""

    @pytest.fixture
    def engine(self):
        """创建测试引擎"""
        with patch('jarvis.core.chat_engine.memory_store'):
            engine = ChatEngine()
            return engine

    def test_build_prompt_with_no_settings(self, engine):
        """Prompt files loaded from workspace/prompts/"""
        settings = SystemPromptSettings()
        prompt = engine._build_system_prompt(settings)
        # No prompt files in test work_folder → only dynamic sections
        assert isinstance(prompt, str)

    def test_build_prompt_with_persona(self, engine):
        """测试带角色设定的 prompt（动态注入）"""
        settings = SystemPromptSettings(persona="你是贾维斯，一个智能助手")
        prompt = engine._build_system_prompt(settings)
        assert "## 角色设定" in prompt
        assert "你是贾维斯，一个智能助手" in prompt

    def test_build_prompt_with_abilities(self, engine):
        """测试带能力说明的 prompt（动态注入）"""
        settings = SystemPromptSettings(abilities="可以帮助写代码、回答问题")
        prompt = engine._build_system_prompt(settings)
        assert "## 能力说明" in prompt
        assert "可以帮助写代码、回答问题" in prompt

    def test_build_prompt_with_memory(self, engine):
        """测试带记忆说明的 prompt（动态注入）"""
        settings = SystemPromptSettings(memory="会记住用户的偏好设置")
        prompt = engine._build_system_prompt(settings)
        assert "## 记忆说明" in prompt
        assert "会记住用户的偏好设置" in prompt

    def test_build_prompt_with_tools_extra(self, engine):
        """Tools extra removed from dynamic injection — now in prompt files"""
        settings = SystemPromptSettings(tools="test")
        prompt = engine._build_system_prompt(settings)
        # Tools moved to file-based prompts, not injected dynamically
        assert isinstance(prompt, str)

    def test_build_prompt_with_work_folder(self, engine):
        """Work folder substituted via {work_folder} in prompt files (no files→empty)"""
        settings = SystemPromptSettings(work_folder="/home/project")
        prompt = engine._build_system_prompt(settings)
        assert isinstance(prompt, str)

    def test_build_prompt_with_all_settings(self, engine):
        """测试带所有动态设置的 prompt"""
        settings = SystemPromptSettings(
            persona="你是助手",
            abilities="帮助Coding",
            memory="记忆上下文",
            tools="补充说明",
            work_folder="/custom/path"
        )
        prompt = engine._build_system_prompt(settings)
        assert "## 角色设定" in prompt
        assert "## 能力说明" in prompt
        assert "## 记忆说明" in prompt


class TestChatMethod:
    """测试 chat() 方法的核心逻辑"""

    @pytest.fixture
    def engine(self):
        """创建测试引擎"""
        with patch('jarvis.core.chat_engine.memory_store'):
            engine = ChatEngine()
            return engine

    @pytest.mark.asyncio
    async def test_chat_creates_new_conversation(self, engine):
        """测试 chat 创建新对话"""
        # Mock dependencies
        engine.memory.get_conversation = AsyncMock(return_value=None)
        engine.memory.retrieve = AsyncMock(return_value=[])
        engine.memory.save_conversation = AsyncMock(return_value=True)
        engine._load_prompt_settings = AsyncMock(return_value=SystemPromptSettings())
        engine.router.chat = AsyncMock(return_value=MagicMock(content="Hello! How can I help?"))
        engine.tool_parser.has_tool_calls = MagicMock(return_value=False)
        engine._save_conversation_to_file = AsyncMock()

        # Execute
        result = await engine.chat("Hello")

        # Verify
        assert result == "Hello! How can I help?"
        assert engine.current_conversation is not None
        assert len(engine.current_conversation.messages) == 2  # user + assistant

    @pytest.mark.asyncio
    async def test_chat_loads_existing_conversation(self, engine):
        """测试 chat 加载已有对话"""
        from datetime import datetime
        # Mock existing conversation with proper datetime
        existing_conv = {
            "conversation_id": "conv_123",
            "user_id": "user1",
            "messages": [
                {"role": "user", "content": "First message", "message_id": "1", "timestamp": datetime.now()}
            ],
            "context": {}
        }
        engine.memory.get_conversation = AsyncMock(return_value=existing_conv)
        engine.memory.retrieve = AsyncMock(return_value=[])
        engine.memory.save_conversation = AsyncMock(return_value=True)
        engine._load_prompt_settings = AsyncMock(return_value=SystemPromptSettings())
        engine.router.chat = AsyncMock(return_value=MagicMock(content="Second response"))
        engine.tool_parser.has_tool_calls = MagicMock(return_value=False)
        engine._save_conversation_to_file = AsyncMock()

        # Execute
        result = await engine.chat("Second message", conversation_id="conv_123")

        # Verify
        assert result == "Second response"
        assert engine.current_conversation.conversation_id == "conv_123"

    @pytest.mark.asyncio
    async def test_chat_with_memories(self, engine):
        """测试 chat 检索记忆"""
        mock_memories = [
            {"content": "User prefers dark mode", "key": "theme_pref"},
            {"content": "User works on Mac", "key": "work_env"}
        ]
        engine.memory.get_conversation = AsyncMock(return_value=None)
        engine.memory.retrieve = AsyncMock(return_value=mock_memories)
        engine.memory.save_conversation = AsyncMock(return_value=True)
        engine._load_prompt_settings = AsyncMock(return_value=SystemPromptSettings())
        engine.router.chat = AsyncMock(return_value=MagicMock(content="Response"))
        engine.tool_parser.has_tool_calls = MagicMock(return_value=False)
        engine._save_conversation_to_file = AsyncMock()

        result = await engine.chat("What's my preference?")

        assert result == "Response"
        # Verify retrieve was called
        engine.memory.retrieve.assert_called_once()

    @pytest.mark.asyncio
    async def test_chat_saves_conversation(self, engine):
        """测试 chat 保存对话"""
        engine.memory.get_conversation = AsyncMock(return_value=None)
        engine.memory.retrieve = AsyncMock(return_value=[])
        engine.memory.save_conversation = AsyncMock(return_value=True)
        engine._load_prompt_settings = AsyncMock(return_value=SystemPromptSettings())
        engine.router.chat = AsyncMock(return_value=MagicMock(content="Response"))
        engine.tool_parser.has_tool_calls = MagicMock(return_value=False)
        engine._save_conversation_to_file = AsyncMock()

        await engine.chat("Hello")

        # Verify save was called
        engine.memory.save_conversation.assert_called_once()
        engine._save_conversation_to_file.assert_called_once()

    @pytest.mark.asyncio
    async def test_chat_handles_save_memory_request(self, engine):
        """测试 chat 保存记忆请求"""
        engine.memory.get_conversation = AsyncMock(return_value=None)
        engine.memory.retrieve = AsyncMock(return_value=[])
        engine.memory.save_conversation = AsyncMock(return_value=True)
        engine.memory.save = AsyncMock(return_value=True)
        engine._load_prompt_settings = AsyncMock(return_value=SystemPromptSettings())
        engine.router.chat = AsyncMock(return_value=MagicMock(content="OK, I remember that"))
        engine.tool_parser.has_tool_calls = MagicMock(return_value=False)
        engine._save_conversation_to_file = AsyncMock()

        # Need > 10 chars and contain "记住"
        await engine.chat("请记住我的名字是小明，谢谢")

        # Verify memory save was called for "记住" request
        engine.memory.save.assert_called_once()

    @pytest.mark.asyncio
    async def test_chat_with_tool_calls_iteration(self, engine):
        """测试 chat 工具调用迭代循环"""
        from jarvis.core.tool_parser import ToolCall

        # First response has tool call, second response is final
        tool_call_response = '{"tool": "file", "params": {"action": "read", "path": "test.txt"}}'
        final_response = "File content: Hello world"

        engine.memory.get_conversation = AsyncMock(return_value=None)
        engine.memory.retrieve = AsyncMock(return_value=[])
        engine.memory.save_conversation = AsyncMock(return_value=True)
        engine._load_prompt_settings = AsyncMock(return_value=SystemPromptSettings())
        # First call returns tool call, second call returns final response
        engine.router.chat = AsyncMock(side_effect=[
            MagicMock(content=tool_call_response),
            MagicMock(content=final_response)
        ])
        engine.tool_parser.has_tool_calls = MagicMock(return_value=True)
        engine.tool_parser.parse = MagicMock(side_effect=[
            [ToolCall(tool="file", action="read", params={"path": "test.txt"}, raw='{}')],
            []
        ])
        engine.task_executor.execute_step = AsyncMock(return_value={"status": "success", "content": "file content"})
        engine._save_conversation_to_file = AsyncMock()

        result = await engine.chat("Read the file")

        assert result == final_response
        assert engine.task_executor.execute_step.called

    @pytest.mark.asyncio
    async def test_chat_max_tool_iterations_warning(self, engine):
        """测试 chat 达到最大迭代次数警告"""
        from jarvis.core.tool_parser import ToolCall
        # Make has_tool_calls always return True to trigger max iterations
        engine.memory.get_conversation = AsyncMock(return_value=None)
        engine.memory.retrieve = AsyncMock(return_value=[])
        engine.memory.save_conversation = AsyncMock(return_value=True)
        engine._load_prompt_settings = AsyncMock(return_value=SystemPromptSettings())
        engine.router.chat = AsyncMock(return_value=MagicMock(content="Response"))
        engine.tool_parser.has_tool_calls = MagicMock(return_value=True)
        engine.tool_parser.parse = MagicMock(return_value=[
            ToolCall(tool="file", action="read", params={"path": "test.txt"}, raw='{}')
        ])
        engine.task_executor.execute_step = AsyncMock(return_value={"status": "success"})
        engine._save_conversation_to_file = AsyncMock()

        # Should complete without error (just warning)
        result = await engine.chat("Read file")

        assert result == "Response"

    @pytest.mark.asyncio
    async def test_chat_tool_execution_error_handling(self, engine):
        """测试 chat 工具执行错误处理"""
        from jarvis.core.tool_parser import ToolCall

        engine.memory.get_conversation = AsyncMock(return_value=None)
        engine.memory.retrieve = AsyncMock(return_value=[])
        engine.memory.save_conversation = AsyncMock(return_value=True)
        engine._load_prompt_settings = AsyncMock(return_value=SystemPromptSettings())
        engine.router.chat = AsyncMock(return_value=MagicMock(content="Done", content_blocks=[]))
        engine.tool_parser.has_tool_calls = MagicMock(side_effect=[True, False, False])
        engine.tool_parser.parse = MagicMock(side_effect=[
            [ToolCall(tool="file", action="read", params={"path": "test.txt"}, raw='{}')],
            []
        ])
        # Simulate tool execution error
        engine.task_executor.execute_step = AsyncMock(side_effect=Exception("File not found"))
        engine._save_conversation_to_file = AsyncMock()

        # Should handle error gracefully and continue
        result = await engine.chat("Read file")

        assert result == "Done"

    @pytest.mark.asyncio
    async def test_chat_conversation_not_exists(self, engine):
        """测试 chat 对话不存在时的处理"""
        # Mock get_conversation returning None for a specific conversation_id
        engine.memory.get_conversation = AsyncMock(return_value=None)
        engine.memory.retrieve = AsyncMock(return_value=[])
        engine.memory.save_conversation = AsyncMock(return_value=True)
        engine._load_prompt_settings = AsyncMock(return_value=SystemPromptSettings())
        engine.router.chat = AsyncMock(return_value=MagicMock(content="New conversation response"))
        engine.tool_parser.has_tool_calls = MagicMock(return_value=False)
        engine._save_conversation_to_file = AsyncMock()

        result = await engine.chat("Hello", conversation_id="nonexistent_conv")

        assert result == "New conversation response"
        # Should create new conversation with given id
        assert engine.current_conversation.conversation_id == "nonexistent_conv"


class TestSaveConversationToFile:
    """测试 _save_conversation_to_file 方法"""

    @pytest.fixture
    def engine(self):
        """创建测试引擎"""
        with patch('jarvis.core.chat_engine.memory_store'):
            engine = ChatEngine()
            return engine

    @pytest.mark.asyncio
    async def test_save_conversation_creates_file(self, engine, tmp_path):
        """测试保存对话到文件"""
        import json
        from jarvis.core.entities import Conversation, Message
        from datetime import datetime

        # Setup
        engine.work_folder = str(tmp_path)
        engine.current_conversation = Conversation(
            conversation_id="test_conv",
            user_id="test_user"
        )
        engine.current_conversation.add_message("user", "Hello")
        engine.current_conversation.add_message("assistant", "Hi there")

        # Execute
        await engine._save_conversation_to_file()

        # Verify file exists
        file_path = tmp_path / "conversations" / "test_conv.json"
        assert file_path.exists()

        # Verify content
        with open(file_path, 'r') as f:
            data = json.load(f)
        assert data["conversation_id"] == "test_conv"
        assert data["user_id"] == "test_user"
        assert len(data["messages"]) == 2
        assert "system_prompt" in data

    @pytest.mark.asyncio
    async def test_save_conversation_handles_no_current_conversation(self, engine, tmp_path):
        """测试没有当前对话时不保存"""
        engine.work_folder = str(tmp_path)
        engine.current_conversation = None

        # Should not raise, just silently fail
        await engine._save_conversation_to_file()

        # No file should be created
        file_path = tmp_path / "conversations" / "test_conv.json"
        assert not file_path.exists()


class TestListModels:
    """测试 list_models 方法"""

    @pytest.fixture
    def engine(self):
        """创建测试引擎"""
        with patch('jarvis.core.chat_engine.memory_store'):
            engine = ChatEngine()
            return engine

    @pytest.mark.asyncio
    async def test_list_models(self, engine):
        """测试列出模型"""
        mock_models = [{"name": "gpt-4", "provider": "openai"}]
        engine.router.list_models = AsyncMock(return_value=mock_models)

        result = await engine.list_models()

        assert result == mock_models
        engine.router.list_models.assert_called_once_with(force_refresh=False)

    @pytest.mark.asyncio
    async def test_list_models_with_force_refresh(self, engine):
        """测试强制刷新模型列表"""
        mock_models = [{"name": "gpt-4", "provider": "openai"}]
        engine.router.list_models = AsyncMock(return_value=mock_models)

        await engine.list_models(force_refresh=True)

        engine.router.list_models.assert_called_once_with(force_refresh=True)


class TestStreamChat:
    """测试 stream_chat 方法"""

    @pytest.fixture
    def engine(self):
        """创建测试引擎"""
        with patch('jarvis.core.chat_engine.memory_store'):
            engine = ChatEngine()
            return engine

    @pytest.mark.asyncio
    async def test_stream_chat_no_tool_calls(self, engine):
        """测试流式对话无工具调用"""
        engine.memory.get_conversation = AsyncMock(return_value=None)
        engine.memory.retrieve = AsyncMock(return_value=[])
        engine.memory.save_conversation = AsyncMock(return_value=True)
        engine._load_prompt_settings = AsyncMock(return_value=SystemPromptSettings())

        async def mock_stream_full(messages, model=None):
            yield {"type": "text", "content": "Hello, stream response!"}
            yield {"type": "message_stop"}

        engine.router.chat_stream_full = mock_stream_full
        engine._save_conversation_to_file = AsyncMock()

        # 执行流式对话
        result = []
        async for token in engine.stream_chat("Hello"):
            result.append(token)
        response = "".join(result)

        assert response == "Hello, stream response!"
        assert engine.current_conversation is not None

    @pytest.mark.asyncio
    async def test_stream_chat_with_conversation_id(self, engine):
        """测试带 conversation_id 的流式对话"""
        from datetime import datetime
        existing_conv = {
            "conversation_id": "conv_stream",
            "user_id": "user1",
            "messages": [
                {"role": "user", "content": "Previous message", "message_id": "1", "timestamp": datetime.now()}
            ],
            "context": {}
        }
        engine.memory.get_conversation = AsyncMock(return_value=existing_conv)
        engine.memory.save_conversation = AsyncMock(return_value=True)
        engine._load_prompt_settings = AsyncMock(return_value=SystemPromptSettings())

        async def mock_stream_full(messages, model=None):
            yield {"type": "text", "content": "Stream response"}
            yield {"type": "message_stop"}

        engine.router.chat_stream_full = mock_stream_full
        engine._save_conversation_to_file = AsyncMock()

        result = []
        async for token in engine.stream_chat("New message", conversation_id="conv_stream"):
            result.append(token)

        assert "".join(result) == "Stream response"
        assert engine.current_conversation.conversation_id == "conv_stream"

    @pytest.mark.asyncio
    async def test_stream_chat_saves_conversation(self, engine):
        """测试流式对话保存对话"""
        engine.memory.get_conversation = AsyncMock(return_value=None)
        engine.memory.save_conversation = AsyncMock(return_value=True)
        engine._load_prompt_settings = AsyncMock(return_value=SystemPromptSettings())

        async def mock_stream_full(messages, model=None):
            yield {"type": "text", "content": "Saved response"}
            yield {"type": "message_stop"}

        engine.router.chat_stream_full = mock_stream_full
        engine._save_conversation_to_file = AsyncMock()

        async for _ in engine.stream_chat("Hello"):
            pass

        engine.memory.save_conversation.assert_called_once()
        engine._save_conversation_to_file.assert_called_once()


class TestStreamChatWithMessages:
    """测试 stream_chat_with_messages 方法"""

    @pytest.fixture
    def engine(self):
        """创建测试引擎"""
        with patch('jarvis.core.chat_engine.memory_store'):
            engine = ChatEngine()
            return engine

    @pytest.mark.asyncio
    async def test_stream_with_messages(self, engine):
        """测试传入消息历史的流式对话"""
        engine.memory.get_conversation = AsyncMock(return_value=None)
        engine.memory.save_conversation = AsyncMock(return_value=True)
        engine._load_prompt_settings = AsyncMock(return_value=SystemPromptSettings())

        async def mock_stream_full(messages, model=None):
            yield {"type": "text", "content": "Response with history"}
            yield {"type": "message_stop"}

        engine.router.chat_stream_full = mock_stream_full
        engine._save_conversation_to_file = AsyncMock()

        messages_history = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"}
        ]

        result = []
        async for token in engine.stream_chat_with_messages("Follow up", messages_history):
            result.append(token)

        assert "".join(result) == "Response with history"

    @pytest.mark.asyncio
    async def test_stream_with_messages_reuses_conversation(self, engine):
        """测试传入 conversation_id 时复用对话"""
        from datetime import datetime
        existing_conv = {
            "conversation_id": "conv_abc",
            "user_id": "user1",
            "messages": [
                {"role": "user", "content": "First", "message_id": "1", "timestamp": datetime.now()}
            ],
            "context": {}
        }
        engine.memory.get_conversation = AsyncMock(return_value=existing_conv)
        engine.memory.save_conversation = AsyncMock(return_value=True)
        engine._load_prompt_settings = AsyncMock(return_value=SystemPromptSettings())

        async def mock_stream_full(messages, model=None):
            yield {"type": "text", "content": "Continued"}
            yield {"type": "message_stop"}

        engine.router.chat_stream_full = mock_stream_full
        engine._save_conversation_to_file = AsyncMock()

        messages_history = [{"role": "user", "content": "Second"}]

        async for _ in engine.stream_chat_with_messages("Third", messages_history, conversation_id="conv_abc"):
            pass

        assert engine.current_conversation.conversation_id == "conv_abc"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])