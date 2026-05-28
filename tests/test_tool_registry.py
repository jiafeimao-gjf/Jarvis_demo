# tests/test_tool_registry.py
"""测试工具注册表"""
import pytest
from jarvis.core.tool_registry import ToolRegistry, ToolDefinition, ToolParam


class TestToolRegistry:
    """测试 ToolRegistry"""

    def test_register_and_get_tool(self):
        """测试工具注册和获取"""
        registry = ToolRegistry()
        tool = registry.get("file")
        assert tool is not None
        assert tool.name == "file"
        assert "read" in tool.parameters or "action" in tool.parameters

    def test_list_tools(self):
        """测试列出所有工具"""
        registry = ToolRegistry()
        tools = registry.list_tools()
        assert len(tools) > 0
        tool_names = [t.name for t in tools]
        assert "file" in tool_names
        assert "bash" in tool_names
        assert "browser" in tool_names

    def test_get_tool_names(self):
        """测试获取工具名称列表"""
        registry = ToolRegistry()
        names = registry.get_tool_names()
        assert "file" in names
        assert "bash" in names
        assert "browser" in names
        assert "desktop" in names
        assert "api" in names
        assert "tool" in names

    def test_build_schema_for_llm(self):
        """测试构建 LLM 工具描述"""
        registry = ToolRegistry()
        schema = registry.build_schema_for_llm()
        assert "## 可用工具" in schema
        assert "### 文件操作" in schema
        assert "tool: file" in schema
        assert "### 系统命令" in schema
        assert "tool: bash" in schema

    def test_build_json_schema(self):
        """测试构建 JSON Schema"""
        registry = ToolRegistry()
        schema = registry.build_json_schema()
        assert "type" in schema
        assert "properties" in schema
        assert "file" in schema["properties"]
        assert "bash" in schema["properties"]

    def test_get_nonexistent_tool(self):
        """测试获取不存在的工具"""
        registry = ToolRegistry()
        tool = registry.get("nonexistent")
        assert tool is None


class TestToolDefinition:
    """测试 ToolDefinition"""

    def test_create_tool_definition(self):
        """测试创建工具定义"""
        tool = ToolDefinition(
            name="test_tool",
            description="A test tool",
            category="Test",
            parameters={
                "action": ToolParam("action", "The action", required=True),
                "path": ToolParam("path", "File path")
            }
        )
        assert tool.name == "test_tool"
        assert tool.description == "A test tool"
        assert tool.category == "Test"
        assert "action" in tool.parameters
        assert "path" in tool.parameters


if __name__ == "__main__":
    pytest.main([__file__, "-v"])