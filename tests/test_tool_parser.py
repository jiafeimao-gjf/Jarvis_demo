# tests/test_tool_parser.py
"""测试工具调用解析器"""
import pytest
from jarvis.core.tool_parser import ToolCallParser, ToolCall


class TestToolCallParser:
    """测试 ToolCallParser"""

    def setup_method(self):
        """每个测试方法前设置"""
        self.parser = ToolCallParser("/tmp")

    def test_parse_standard_format(self):
        """测试标准格式解析"""
        text = '{"tool": "file", "params": {"action": "read", "path": "test.txt"}}'
        calls = self.parser.parse(text)
        assert len(calls) == 1
        assert calls[0].tool == "file"
        assert calls[0].action == "read"
        assert calls[0].params["path"] == "test.txt"

    def test_parse_minimax_format(self):
        """测试 MiniMax 格式解析"""
        text = '{"name": "bash", "parameters": {"command": "ls -la"}}'
        calls = self.parser.parse(text)
        assert len(calls) == 1
        assert calls[0].tool == "bash"
        assert calls[0].params["command"] == "ls -la"

    def test_parse_multiple_calls(self):
        """测试多个工具调用解析"""
        text = '''
        [
            {"tool": "file", "params": {"action": "read", "path": "test.txt"}},
            {"tool": "bash", "params": {"command": "ls"}}
        ]
        '''
        calls = self.parser.parse(text)
        assert len(calls) == 2
        assert calls[0].tool == "file"
        assert calls[1].tool == "bash"

    def test_parse_no_tool_calls(self):
        """测试无工具调用的文本"""
        text = "Hello, how are you?"
        calls = self.parser.parse(text)
        assert len(calls) == 0

    def test_has_tool_calls_true(self):
        """测试检测到工具调用"""
        text = '{"tool": "file", "params": {"action": "read"}}'
        assert self.parser.has_tool_calls(text) is True

    def test_has_tool_calls_false(self):
        """测试未检测到工具调用"""
        text = "Just a normal text without any tool calls."
        assert self.parser.has_tool_calls(text) is False

    def test_parse_with_extra_text(self):
        """测试带有额外文本的工具调用"""
        text = '''
        Let me read that file for you:
        {"tool": "file", "params": {"action": "read", "path": "test.txt"}}
        '''
        calls = self.parser.parse(text)
        assert len(calls) == 1
        assert calls[0].tool == "file"

    def test_parse_invalid_json(self):
        """测试无效 JSON"""
        text = "This is not valid JSON { tool: "
        calls = self.parser.parse(text)
        assert len(calls) == 0


class TestToolCall:
    """测试 ToolCall 数据类"""

    def test_create_tool_call(self):
        """测试创建 ToolCall"""
        call = ToolCall(
            tool="file",
            action="read",
            params={"path": "test.txt"},
            raw='{"tool": "file", "params": {"path": "test.txt"}}'
        )
        assert call.tool == "file"
        assert call.action == "read"
        assert call.params["path"] == "test.txt"

    def test_tool_call_with_empty_params(self):
        """测试空参数"""
        call = ToolCall(tool="bash", action="execute", params={}, raw="{}")
        assert call.tool == "bash"
        assert call.params == {}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])