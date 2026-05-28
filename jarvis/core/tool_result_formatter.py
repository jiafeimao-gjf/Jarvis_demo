# jarvis/core/tool_result_formatter.py
"""工具结果格式化器 - 将工具执行结果格式化为 LLM 可消费的格式"""
import json
from typing import Any
from dataclasses import dataclass


@dataclass
class FormattedToolResult:
    """格式化后的工具结果"""
    tool: str
    action: str
    params: dict
    status: str
    result: Any
    error: str = ""
    tool_use_id: str = ""  # 用于追踪原始 tool_use block 的 id

    def to_message(self) -> dict:
        """转换为发送给 LLM 的消息格式 (Anthropic tool_result 格式)"""
        content = {
            "type": "tool_result",
            "tool_use_id": self.tool_use_id,
            "content": self._format_content()
        }
        return content

    def _format_content(self) -> str:
        """格式化结果内容为文本"""
        if self.error:
            return f"[TOOL_ERROR] {self.error}"
        result_str = self.result if isinstance(self.result, str) else json.dumps(self.result, ensure_ascii=False)
        return f"[TOOL_RESULT] {result_str}"


class ToolResultFormatter:
    """格式化工具执行结果为 LLM 消息"""

    @staticmethod
    def format(tool: str, action: str, params: dict, result: Any, tool_use_id: str = "") -> dict:
        """格式化单个工具结果 - 返回 Anthropic tool_result 格式的字典"""
        status = "success"
        error = ""
        output = result

        if isinstance(result, dict):
            status = result.get("status", "success")
            if status == "error":
                error = result.get("message", str(result))
            output = result.get("result") or result.get("message") or result

        formatted = FormattedToolResult(
            tool=tool,
            action=action,
            params=params,
            status=status,
            result=output,
            error=error,
            tool_use_id=tool_use_id
        )
        return formatted.to_message()

    @staticmethod
    def format_batch(results: list[tuple]) -> list[dict]:
        """格式化多个工具结果"""
        formatted_results = []
        for item in results:
            if len(item) >= 4:
                tool, action, params, result = item[0], item[1], item[2], item[3]
            elif len(item) == 3:
                tool = item[0].tool if hasattr(item[0], 'tool') else str(item[0])
                action = item[0].action if hasattr(item[0], 'action') else ""
                params = item[1]
                result = item[2]
            else:
                continue
            formatted_results.append(ToolResultFormatter.format(tool, action, params, result))
        return formatted_results