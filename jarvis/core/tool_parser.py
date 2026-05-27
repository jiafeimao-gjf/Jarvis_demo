# jarvis/core/tool_parser.py
"""工具调用解析器 - 从 LLM 响应中解析工具调用"""
import json
import re
from dataclasses import dataclass
from typing import Optional, Any
from jarvis.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ToolCall:
    """解析后的工具调用结构"""
    tool: str
    action: str
    params: dict
    raw: str  # 原始 JSON 字符串


class ToolCallParser:
    """从 LLM 文本响应中解析工具调用"""

    # 支持的工具列表
    VALID_TOOLS = {"file", "browser", "desktop", "api", "tool", "bash"}

    # JSON 数组模式: [{}, {}]
    JSON_ARRAY_PATTERN = re.compile(r'\[\s*\{.*\}\s*\]', re.DOTALL)

    # JSON 对象模式: {"tool": "...", "params": {...}}
    JSON_OBJECT_PATTERN = re.compile(
        r'\{\s*"tool"\s*:\s*"([^"]+)"\s*,\s*"params"\s*:\s*\{[^}]+\}',
        re.DOTALL
    )

    def __init__(self, work_folder: Optional[str] = None):
        self.work_folder = work_folder

    def parse(self, text: str) -> list[ToolCall]:
        """从 LLM 响应文本中提取工具调用"""
        tool_calls = []

        # 清理文本 - 移除 markdown 代码块标记
        cleaned_text = re.sub(r'```json\s*', '', text)
        cleaned_text = re.sub(r'```\s*', '', cleaned_text)

        # 尝试 JSON 数组格式: [{}, {}]
        try:
            # 先找整个 JSON 数组
            array_match = re.search(r'\[[\s\S]*\]', cleaned_text)
            if array_match:
                calls = json.loads(array_match.group())
                if isinstance(calls, list):
                    for call in calls:
                        tool_call = self._validate_and_create(call, array_match.group())
                        if tool_call:
                            tool_calls.append(tool_call)
        except json.JSONDecodeError:
            pass

        # 尝试直接找所有包含 "tool" 的 JSON 对象
        if not tool_calls:
            # 使用括号匹配找到完整的 JSON 对象
            json_pattern = re.compile(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}')
            matches = json_pattern.findall(cleaned_text)
            for match in matches:
                if '"tool"' in match and '"params"' in match:
                    try:
                        call = json.loads(match)
                        tool_call = self._validate_and_create(call, match)
                        if tool_call:
                            tool_calls.append(tool_call)
                    except json.JSONDecodeError:
                        continue

        logger.debug(f"从响应中解析到 {len(tool_calls)} 个工具调用")
        return tool_calls

    def _validate_and_create(self, call: dict, raw: str) -> Optional[ToolCall]:
        """验证并创建 ToolCall"""
        if "tool" not in call:
            return None

        tool_name = call.get("tool", "")
        if tool_name not in self.VALID_TOOLS:
            logger.warning(f"未知工具: {tool_name}")
            return None

        params = call.get("params", {})
        if not isinstance(params, dict):
            logger.warning(f"{tool_name} 的 params 参数类型无效")
            return None

        # 提取 action
        action = params.get("action", "")
        if not action:
            # 如果没有 action，尝试从顶层获取
            action = call.get("action", "")

        return ToolCall(
            tool=tool_name,
            action=action,
            params=params,
            raw=raw
        )

    def has_tool_calls(self, text: str) -> bool:
        """快速检查文本是否包含可能的工具调用"""
        return '"tool"' in text and '"params"' in text


@dataclass
class ToolCallResult:
    """工具执行结果"""
    tool: str
    action: str
    params: dict
    status: str
    result: Any
    error: Optional[str] = None

    def to_message(self) -> str:
        """转换为发送给 LLM 的消息格式"""
        content = {
            "tool": self.tool,
            "action": self.action,
            "status": self.status,
            "result": self.result
        }
        if self.error:
            content["error"] = self.error
        return f"[TOOL_RESULT] {json.dumps(content, ensure_ascii=False)}"