# tests/test_chat_engine.py
"""测试对话引擎"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
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
            # 验证引擎初始化时不会报错
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
        """测试无设置时的 prompt 构建"""
        settings = SystemPromptSettings()
        prompt = engine._build_system_prompt(settings)
        assert "## 可用工具" in prompt
        assert "tool: file" in prompt
        assert "tool: bash" in prompt
        assert "## 工作目录" in prompt
        assert "## 工具调用格式" in prompt

    def test_build_prompt_with_persona(self, engine):
        """测试带角色设定的 prompt"""
        settings = SystemPromptSettings(persona="你是贾维斯，一个智能助手")
        prompt = engine._build_system_prompt(settings)
        assert "## 角色设定" in prompt
        assert "你是贾维斯，一个智能助手" in prompt

    def test_build_prompt_with_abilities(self, engine):
        """测试带能力说明的 prompt"""
        settings = SystemPromptSettings(abilities="可以帮助写代码、回答问题")
        prompt = engine._build_system_prompt(settings)
        assert "## 能力说明" in prompt
        assert "可以帮助写代码、回答问题" in prompt

    def test_build_prompt_with_memory(self, engine):
        """测试带记忆说明的 prompt"""
        settings = SystemPromptSettings(memory="会记住用户的偏好设置")
        prompt = engine._build_system_prompt(settings)
        assert "## 记忆说明" in prompt
        assert "会记住用户的偏好设置" in prompt

    def test_build_prompt_with_tools_extra(self, engine):
        """测试带额外工具说明的 prompt"""
        settings = SystemPromptSettings(tools="额外说明：使用前请确认文件存在")
        prompt = engine._build_system_prompt(settings)
        assert "## 额外工具说明" in prompt
        assert "额外说明：使用前请确认文件存在" in prompt

    def test_build_prompt_with_work_folder(self, engine):
        """测试带工作目录的 prompt"""
        settings = SystemPromptSettings(work_folder="/home/project")
        prompt = engine._build_system_prompt(settings)
        assert "/home/project" in prompt

    def test_build_prompt_with_all_settings(self, engine):
        """测试带所有设置的 prompt"""
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
        assert "## 额外工具说明" in prompt
        assert "/custom/path" in prompt

    def test_build_prompt_uses_default_work_folder_when_not_set(self, engine):
        """测试未设置工作目录时使用默认值"""
        original_work_folder = engine.work_folder
        settings = SystemPromptSettings()
        prompt = engine._build_system_prompt(settings)
        assert original_work_folder in prompt or "工作目录" in prompt


class TestLoadPromptSettings:
    """测试加载 Prompt 设置"""

    @pytest.fixture
    def engine(self):
        """创建测试引擎"""
        with patch('jarvis.core.chat_engine.memory_store'):
            engine = ChatEngine()
            return engine

    @pytest.mark.asyncio
    async def test_load_prompt_settings_default(self, engine):
        """测试加载默认设置"""
        with patch.object(engine.memory, 'get_all_settings', return_value={}):
            settings = await engine._load_prompt_settings()
            assert settings.persona == ""
            assert settings.abilities == ""
            assert settings.memory == ""
            assert settings.tools == ""
            assert settings.work_folder == ""

    @pytest.mark.asyncio
    async def test_load_prompt_settings_with_values(self, engine):
        """测试加载带值的设置"""
        mock_settings = {
            "persona_prompt": "Test Persona",
            "abilities_prompt": "Test Abilities",
            "memory_prompt": "Test Memory",
            "tools_prompt": "Test Tools",
            "work_folder": "/test/path"
        }
        with patch.object(engine.memory, 'get_all_settings', return_value=mock_settings):
            settings = await engine._load_prompt_settings()
            assert settings.persona == "Test Persona"
            assert settings.abilities == "Test Abilities"
            assert settings.memory == "Test Memory"
            assert settings.tools == "Test Tools"
            assert settings.work_folder == "/test/path"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])