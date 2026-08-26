# tests/test_chat_engine.py
"""测试对话引擎"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass
from jarvis.core.chat_engine import ChatEngine, SystemPromptSettings


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
        engine.memory.update_conversation_topic = AsyncMock(return_value=True)
        engine._load_prompt_settings = AsyncMock(return_value=SystemPromptSettings())
        engine.router.chat = AsyncMock(return_value=MagicMock(content="Hello! How can I help?"))
        engine.tool_parser.has_tool_calls = MagicMock(return_value=False)
        engine._save_conversation_to_file = AsyncMock()

        # Execute (mock topic generation to avoid LLM call)
        with patch('jarvis.core.chat_engine.generate_topic', new=AsyncMock(return_value="测试主题")):
            result = await engine.chat("Hello")

        # Verify — chat() now returns dict {text, topic}
        assert result["text"] == "Hello! How can I help?"
        assert result["topic"] == "测试主题"
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
            "topic": "已存在的主题",
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

        # Execute — pre-existing topic should NOT be overwritten
        with patch('jarvis.core.chat_engine.generate_topic', new=AsyncMock(return_value="新主题")):
            result = await engine.chat("Second message", conversation_id="conv_123")

        # Verify
        assert result["text"] == "Second response"
        assert result["topic"] == "已存在的主题"  # preserved, not overwritten
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

        with patch('jarvis.core.chat_engine.generate_topic', new=AsyncMock(return_value="测试主题")):
            result = await engine.chat("What's my preference?")

        assert result["text"] == "Response"
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

        with patch('jarvis.core.chat_engine.generate_topic', new=AsyncMock(return_value="测试主题")):
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
        with patch('jarvis.core.chat_engine.generate_topic', new=AsyncMock(return_value="测试主题")):
            await engine.chat("请记住我的名字是小明，谢谢")

        # Verify memory save was called for "记住" request
        engine.memory.save.assert_called_once()

    @pytest.mark.asyncio
    async def test_chat_with_tool_calls_iteration(self, engine):
        """测试 chat 工具调用迭代循环 (PR2 改用 content_blocks tool_use 路径)."""
        tool_use_block = {
            "type": "tool_use",
            "id": "toolu_test1",
            "name": "file",
            "input": {"action": "read", "path": "test.txt"},
        }
        final_response = "File content: Hello world"

        engine.memory.get_conversation = AsyncMock(return_value=None)
        engine.memory.retrieve = AsyncMock(return_value=[])
        engine.memory.save_conversation = AsyncMock(return_value=True)
        engine._load_prompt_settings = AsyncMock(return_value=SystemPromptSettings())
        # Phase 1 返回 tool_use, Phase 2 (runner 内部 LLM) 返回纯文本
        engine.router.chat = AsyncMock(side_effect=[
            MagicMock(
                content="", thinking="",
                content_blocks=[tool_use_block],
            ),
            MagicMock(
                content=final_response, thinking="",
                content_blocks=[{"type": "text", "text": final_response}],
            ),
        ])
        engine.task_executor.execute_step = AsyncMock(
            return_value={"status": "success", "content": "file content"}
        )
        engine._save_conversation_to_file = AsyncMock()

        with patch('jarvis.core.chat_engine.generate_topic', new=AsyncMock(return_value="测试主题")):
            result = await engine.chat("Read the file")

        assert result["text"] == final_response
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
            ToolCall(tool="file", action="read", params={"path": "test.txt"}, raw_input_json='{}')
        ])
        engine.task_executor.execute_step = AsyncMock(return_value={"status": "success"})
        engine._save_conversation_to_file = AsyncMock()

        # Should complete without error (just warning)
        with patch('jarvis.core.chat_engine.generate_topic', new=AsyncMock(return_value="测试主题")):
            result = await engine.chat("Read file")

        assert result["text"] == "Response"

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
            [ToolCall(tool="file", action="read", params={"path": "test.txt"}, raw_input_json='{}')],
            []
        ])
        # Simulate tool execution error
        engine.task_executor.execute_step = AsyncMock(side_effect=Exception("File not found"))
        engine._save_conversation_to_file = AsyncMock()

        # Should handle error gracefully and continue
        with patch('jarvis.core.chat_engine.generate_topic', new=AsyncMock(return_value="测试主题")):
            result = await engine.chat("Read file")

        assert result["text"] == "Done"

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

        with patch('jarvis.core.chat_engine.generate_topic', new=AsyncMock(return_value="测试主题")):
            result = await engine.chat("Hello", conversation_id="nonexistent_conv")

        assert result["text"] == "New conversation response"
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

        async def mock_stream_full(messages, model=None, instance=None, **kwargs):
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

        async def mock_stream_full(messages, model=None, instance=None, **kwargs):
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

        async def mock_stream_full(messages, model=None, instance=None, **kwargs):
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

        async def mock_stream_full(messages, model=None, instance=None, **kwargs):
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

        async def mock_stream_full(messages, model=None, instance=None, **kwargs):
            yield {"type": "text", "content": "Continued"}
            yield {"type": "message_stop"}

        engine.router.chat_stream_full = mock_stream_full
        engine._save_conversation_to_file = AsyncMock()

        messages_history = [{"role": "user", "content": "Second"}]

        async for _ in engine.stream_chat_with_messages("Third", messages_history, conversation_id="conv_abc"):
            pass

        assert engine.current_conversation.conversation_id == "conv_abc"


class TestAgentLoop:
    """chat/stream_chat 经 AgentLoopRunner 接入后的核心行为:

    - assistant turn 必须出现在 tool_result user msg 之前 (修核心 bug)
    - 同一 (tool, params) 重复调用只执行一次 (dedup)
    - iteration > 2 时注入 iteration hint user msg
    - 并行工具执行 (asyncio.gather 路径)
    - 达到 max_iterations 时注入 stop hint
    """

    @pytest.fixture
    def runner_engine(self):
        """带 mock router / task_executor / tool_parser 的 ChatEngine.

        注意: AgentLoopRunner 在 __init__ 时持有了 self.task_executor 的引用,
        替换 ChatEngine.task_executor 不会影响 runner. 这里同时更新 runner
        内部的引用.
        """
        engine = ChatEngine()
        engine.router = MagicMock()
        # 默认 router.chat 是个 AsyncMock, 不带 side_effect
        # 各测试可按需覆盖 side_effect / return_value
        engine.router.chat = AsyncMock(
            return_value=MagicMock(
                content="done", thinking="",
                content_blocks=[{"type": "text", "text": "done"}],
            )
        )
        engine.task_executor = MagicMock()
        engine.task_executor.execute_step = AsyncMock(
            return_value={"status": "success", "content": "ok"}
        )
        engine.tool_parser = MagicMock()
        # 同步更新 runner 的 task_executor 引用
        engine.agent_loop_runner.task_executor = engine.task_executor
        engine.agent_loop_runner.tool_parser = engine.tool_parser
        return engine

    @pytest.mark.asyncio
    async def test_assistant_turn_precedes_tool_result(self, runner_engine):
        """核心 bug 修复: tool_result user msg 之前必须有 assistant turn (含 tool_use)."""
        from jarvis.core.agent_loop import AgentLoopRunner

        # Phase 1: 第一次 LLM 返回 tool_use
        # Phase 2: 再调一次 LLM, 返回纯文本 (无 tool_use)
        runner_engine.router.chat = AsyncMock(side_effect=[
            # 第 2 次迭代 LLM 响应 (Phase 2 后), 无 tool_use
            MagicMock(
                content="完成",
                thinking="",
                content_blocks=[{"type": "text", "text": "完成"}],
            ),
        ])

        messages = [{"role": "user", "content": "读 x.txt"}]
        events = []
        async for ev in runner_engine.agent_loop_runner.run_iterations(
            messages, runner_engine.router,
            model=None, instance=None,
            current_text="",
            current_thinking="",
            current_content_blocks=[
                {"type": "text", "text": ""},
                {"type": "tool_use", "id": "toolu_1", "name": "file",
                 "input": {"action": "read", "path": "x.txt"}},
            ],
            current_tool_uses=[
                {"type": "tool_use", "id": "toolu_1", "name": "file",
                 "input": {"action": "read", "path": "x.txt"}},
            ],
        ):
            events.append(ev)

        # 验证 messages 结构: assistant turn 必须在 tool_result user msg 之前
        # 关键: 是 tool_result user msg 之前, 不是任意 user msg 之前
        roles = [m.get("role") for m in messages]
        # 找到第一个 tool_result 块的位置 (在 user msg.content 内)
        tool_result_user_idx = None
        for i, m in enumerate(messages):
            c = m.get("content")
            if (
                m.get("role") == "user"
                and isinstance(c, list)
                and c
                and isinstance(c[0], dict)
                and c[0].get("type") == "tool_result"
            ):
                tool_result_user_idx = i
                break

        assert tool_result_user_idx is not None, (
            f"应该有 tool_result user msg; got roles={roles}"
        )

        # 找 tool_result 之前最近的 assistant turn, 验证它含 tool_use 块
        prev_assistant_idx = None
        for i in range(tool_result_user_idx - 1, -1, -1):
            if messages[i].get("role") == "assistant":
                prev_assistant_idx = i
                break

        assert prev_assistant_idx is not None, (
            f"tool_result 之前必须有 assistant turn; got roles={roles}"
        )

        # 验证那个 assistant turn 含 tool_use 块
        assistant_content = messages[prev_assistant_idx]["content"]
        assert isinstance(assistant_content, list), (
            f"assistant turn 应该是 content blocks 列表; got {assistant_content}"
        )
        tool_use_blocks = [
            b for b in assistant_content
            if isinstance(b, dict) and b.get("type") == "tool_use"
        ]
        assert len(tool_use_blocks) == 1
        assert tool_use_blocks[0]["id"] == "toolu_1"

        # 验证 tool_result user msg 用结构化 block + tool_use_id
        tool_result_msg = messages[tool_result_user_idx]
        assert tool_result_msg["content"][0]["tool_use_id"] == "toolu_1"

    @pytest.mark.asyncio
    async def test_dedup_duplicate_tool_calls(self, runner_engine):
        """相同 (tool, params) 只执行一次, 第二次记 tool_skipped 事件."""
        from jarvis.core.agent_loop import AgentLoopRunner

        runner_engine.router.chat = AsyncMock(
            return_value=MagicMock(
                content="done", thinking="",
                content_blocks=[{"type": "text", "text": "done"}],
            )
        )

        messages = []
        # 两个相同 tool_use
        dup_uses = [
            {"type": "tool_use", "id": "t1", "name": "bash",
             "input": {"command": "ls"}},
            {"type": "tool_use", "id": "t2", "name": "bash",
             "input": {"command": "ls"}},   # 重复
        ]
        events = []
        async for ev in runner_engine.agent_loop_runner.run_iterations(
            messages, runner_engine.router,
            model=None, instance=None,
            current_text="", current_thinking="",
            current_content_blocks=dup_uses,
            current_tool_uses=dup_uses,
        ):
            events.append(ev)

        tool_calls = [e for e in events if e.get("type") == "tool_call"]
        tool_skipped = [e for e in events if e.get("type") == "tool_skipped"]

        assert len(tool_calls) == 1
        assert len(tool_skipped) == 1
        # execute_step 只被调用 1 次 (而非 2 次)
        assert runner_engine.task_executor.execute_step.await_count == 1

    @pytest.mark.asyncio
    async def test_iteration_hint_injected_after_iter2(self, runner_engine):
        """iteration > 2 时注入 iteration hint (提示 LLM 自检)."""
        from jarvis.core.agent_loop import AgentLoopRunner

        # 让 runner 一直跑 (每次 LLM 都返回 tool_use), 直到 max
        tool_use = {"type": "tool_use", "id": "t1", "name": "bash",
                    "input": {"command": "pwd"}}

        async def llm_side_effect(*args, **kwargs):
            return MagicMock(
                content="", thinking="",
                content_blocks=[tool_use],
            )
        runner_engine.router.chat = AsyncMock(side_effect=llm_side_effect)

        # max_iterations=4 跑得更快
        from jarvis.core.agent_loop import AgentLoopConfig
        runner_engine.agent_loop_runner.config = AgentLoopConfig(
            max_iterations=4,
            provider_protocol="anthropic",
            inject_iteration_hint=True,
            inject_stop_hint_on_max=False,
        )

        messages = []
        events = []
        async for ev in runner_engine.agent_loop_runner.run_iterations(
            messages, runner_engine.router,
            model=None, instance=None,
            current_text="", current_thinking="",
            current_content_blocks=[tool_use],
            current_tool_uses=[tool_use],
        ):
            events.append(ev)

        # 找 iteration hint: 内容含 "工具迭代第"
        hint_count = sum(
            1 for m in messages
            if isinstance(m.get("content"), str)
            and "工具迭代第" in m["content"]
        )
        # iter=2 时不注入 (避免喧宾夺主), iter=3, 4 时注入 → 期望 ≥ 1
        assert hint_count >= 1, f"expected iteration hint, got messages={messages}"

    @pytest.mark.asyncio
    async def test_parallel_tool_execution(self, runner_engine):
        """多个 tool_use 时, 并行执行 (execute_step 被并发 await)."""
        from jarvis.core.agent_loop import AgentLoopRunner

        # 第二次 LLM 返回空 (无 tool_use) 终止
        runner_engine.router.chat = AsyncMock(
            return_value=MagicMock(
                content="done", thinking="",
                content_blocks=[{"type": "text", "text": "done"}],
            )
        )

        tool_uses = [
            {"type": "tool_use", "id": "t1", "name": "bash",
             "input": {"command": "ls"}},
            {"type": "tool_use", "id": "t2", "name": "bash",
             "input": {"command": "pwd"}},
        ]

        messages = []
        events = []
        async for ev in runner_engine.agent_loop_runner.run_iterations(
            messages, runner_engine.router,
            model=None, instance=None,
            current_text="", current_thinking="",
            current_content_blocks=tool_uses,
            current_tool_uses=tool_uses,
        ):
            events.append(ev)

        # 两个工具都被执行
        assert runner_engine.task_executor.execute_step.await_count == 2
        # 两个 tool_call 事件
        tool_calls = [e for e in events if e.get("type") == "tool_call"]
        assert len(tool_calls) == 2

    @pytest.mark.asyncio
    async def test_stop_hint_at_max_iterations(self, runner_engine):
        """达到 max_iterations 时, 注入 stop hint (强制 LLM 终止)."""
        from jarvis.core.agent_loop import AgentLoopConfig

        # max_iterations=2: Phase 1 后, runner 不进入循环 (iteration < max 才进入)
        # 测试用 max=3, 让 runner 跑 1 轮 iter=2 后再 iter=3 触发 stop hint
        tool_use = {"type": "tool_use", "id": "t1", "name": "bash",
                    "input": {"command": "pwd"}}

        call_count = {"n": 0}
        async def llm_side_effect(*args, **kwargs):
            call_count["n"] += 1
            return MagicMock(
                content="", thinking="",
                content_blocks=[tool_use],
            )
        runner_engine.router.chat = AsyncMock(side_effect=llm_side_effect)

        runner_engine.agent_loop_runner.config = AgentLoopConfig(
            max_iterations=3,
            provider_protocol="anthropic",
            inject_iteration_hint=False,
            inject_stop_hint_on_max=True,
        )

        messages = []
        events = []
        async for ev in runner_engine.agent_loop_runner.run_iterations(
            messages, runner_engine.router,
            model=None, instance=None,
            current_text="", current_thinking="",
            current_content_blocks=[tool_use],
            current_tool_uses=[tool_use],
        ):
            events.append(ev)

        # 找 stop hint
        stop_hints = [
            m for m in messages
            if isinstance(m.get("content"), str)
            and "已达最大工具迭代次数" in m["content"]
        ]
        assert len(stop_hints) >= 1, "expected stop hint at max iterations"

        # 最终事件应标记 max_iterations_reached
        result_events = [e for e in events if e.get("type") == "result"]
        assert len(result_events) == 1
        assert result_events[0]["result"].max_iterations_reached is True

    @pytest.mark.asyncio
    async def test_no_tool_uses_returns_immediately(self, runner_engine):
        """空 tool_uses → 不进入循环, 立即 yield result."""
        from jarvis.core.agent_loop import AgentLoopConfig

        runner_engine.agent_loop_runner.config = AgentLoopConfig(
            max_iterations=8,
            provider_protocol="anthropic",
        )

        messages = []
        events = []
        async for ev in runner_engine.agent_loop_runner.run_iterations(
            messages, runner_engine.router,
            model=None, instance=None,
            current_text="hi", current_thinking="",
            current_content_blocks=[{"type": "text", "text": "hi"}],
            current_tool_uses=[],   # 无 tool_uses
        ):
            events.append(ev)

        # 只产出一个 result 事件
        assert len(events) == 1
        assert events[0]["type"] == "result"
        assert events[0]["result"].final_text == "hi"
        # router.chat 不该被调
        assert runner_engine.router.chat.await_count == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])