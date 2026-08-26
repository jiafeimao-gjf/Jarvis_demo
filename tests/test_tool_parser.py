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
            raw_input_json='{"tool": "file", "params": {"path": "test.txt"}}'
        )
        assert call.tool == "file"
        assert call.action == "read"
        assert call.params["path"] == "test.txt"

    def test_tool_call_with_empty_params(self):
        """测试空参数"""
        call = ToolCall(tool="bash", action="execute", params={}, raw_input_json="{}")
        assert call.tool == "bash"
        assert call.params == {}


class TestToolCallIdGeneration:
    """ToolCall.id 兜底哈希生成 + 显式 ID 透传."""

    def test_id_empty_generates_stable_hash(self):
        """空 id 时, __post_init__ 生成 tc-<sha1[:12]>, 格式稳定."""
        call = ToolCall(
            tool="file",
            action="read",
            params={"path": "test.txt"},
        )
        assert call.id != ""
        assert call.id.startswith("tc-")
        assert len(call.id) == len("tc-") + 12   # 12 char hex

    def test_id_hash_stable_for_same_inputs(self):
        """相同 (tool, params) → 相同 id (幂等, 可重放)."""
        a = ToolCall(tool="bash", action="execute",
                     params={"command": "ls /tmp"})
        b = ToolCall(tool="bash", action="execute",
                     params={"command": "ls /tmp"})
        assert a.id == b.id

    def test_id_hash_differs_for_different_inputs(self):
        """不同 params → 不同 id."""
        a = ToolCall(tool="bash", action="execute",
                     params={"command": "ls /tmp"})
        b = ToolCall(tool="bash", action="execute",
                     params={"command": "ls /"})
        assert a.id != b.id

    def test_explicit_id_preserved(self):
        """调用方显式传 id 时, 不被兜底覆盖."""
        call = ToolCall(
            tool="file",
            action="read",
            params={"path": "x.txt"},
            id="toolu_abc123",
        )
        assert call.id == "toolu_abc123"

    def test_params_key_order_does_not_affect_id(self):
        """params 字段顺序不影响 id (sort_keys=True)."""
        a = ToolCall(tool="bash", action="execute",
                     params={"command": "ls", "cwd": "/tmp"})
        b = ToolCall(tool="bash", action="execute",
                     params={"cwd": "/tmp", "command": "ls"})
        assert a.id == b.id

    def test_chinese_params_handled(self):
        """中文参数也能生成稳定 id (utf-8 encoding)."""
        a = ToolCall(tool="file", action="write",
                     params={"path": "中文.txt", "content": "你好"})
        b = ToolCall(tool="file", action="write",
                     params={"path": "中文.txt", "content": "你好"})
        assert a.id == b.id
        assert a.id.startswith("tc-")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])