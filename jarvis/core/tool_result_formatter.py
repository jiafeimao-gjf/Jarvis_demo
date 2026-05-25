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


class ToolResultFormatter:
    """格式化工具执行结果为 LLM 消息"""

    @staticmethod
    def format(tool: str, action: str, params: dict, result: Any) -> str:
        """格式化单个工具结果"""
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
            error=error
        )
        return formatted.to_message()

    @staticmethod
    def format_batch(results: list[tuple]) -> str:
        """格式化多个工具结果"""
        lines = []
        for item in results:
            if len(item) >= 4:
                tool, action, params, result = item[0], item[1], item[2], item[3]
            elif len(item) == 3:
                # Assume (tool, params, result)
                tool = item[0].tool if hasattr(item[0], 'tool') else str(item[0])
                action = item[0].action if hasattr(item[0], 'action') else ""
                params = item[1]
                result = item[2]
            else:
                continue
            lines.append(ToolResultFormatter.format(tool, action, params, result))
        return "\n".join(lines)