# jarvis/core/tool_parser.py
"""工具调用解析器 - 从 LLM 响应中解析工具调用"""
import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Optional, Any
from jarvis.utils.logger import get_logger
from jarvis.core.tool_registry import tool_registry

logger = get_logger(__name__)


@dataclass
class ToolCall:
    """解析后的工具调用结构.

    Fields:
      tool:          工具名 (file / bash / ...)
      action:        操作 (read / write / execute / ...)
      params:        工具参数
      id:            工具调用唯一 ID (Anthropic /v1/messages 返回的 tool_use_id;
                     正则解析路径下若缺失, __post_init__ 兜底生成稳定哈希
                     "tc-<sha1[:12]>", 保证 tool_result 始终能匹配)
      raw_input_json: 原始 JSON 字符串 — 仅供 debug / 持久化, 不要再当 ID 用.
                     字段名变更: 旧名 `raw` 歧义太大 (有时是 id, 有时是 JSON 全文).
    """
    tool: str
    action: str
    params: dict
    id: str = ""
    raw_input_json: str = ""

    def __post_init__(self):
        """id 缺失时生成稳定哈希, 保证 tool_result 始终能配对."""
        if not self.id:
            seed = json.dumps(self.params, sort_keys=True, ensure_ascii=False)
            self.id = "tc-" + hashlib.sha1(
                f"{self.tool}|{seed}".encode("utf-8")
            ).hexdigest()[:12]


class ToolCallParser:
    """从 LLM 文本响应中解析工具调用"""

    # JSON 数组模式: [{}, {}]
    JSON_ARRAY_PATTERN = re.compile(r'\[\s*\{.*\}\s*\]', re.DOTALL)

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

        # 尝试直接找所有包含 "tool" 或 "name" 的 JSON 对象
        if not tool_calls:
            json_pattern = re.compile(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}')
            matches = json_pattern.findall(cleaned_text)
            for match in matches:
                if ('"tool"' in match or '"name"' in match) and ('"params"' in match or '"parameters"' in match):
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
        # 支持两种格式:
        # 1. {"tool": ..., "params": {"action": ..., ...}}
        # 2. {"name": ..., "parameters": {"command": ..., ...}}
        tool_name = call.get("tool") or call.get("name", "")
        if not tool_name:
            return None

        # 使用 tool_registry 获取有效工具列表
        valid_tools = tool_registry.get_tool_names()
        if tool_name not in valid_tools:
            logger.warning(f"未知工具: {tool_name}")
            return None

        # 根据格式获取参数
        raw_params = call.get("params") or call.get("parameters", {})
        if not isinstance(raw_params, dict):
            logger.warning(f"{tool_name} 的 params 参数类型无效")
            return None

        # 提取 action — 保留在 params 中（FileOperationStrategy 需要从 params 读取）
        params = raw_params.copy()
        action = params.get("action", "") or call.get("action", "")

        return ToolCall(
            tool=tool_name,
            action=action,
            params=params,
            id="",            # __post_init__ 兜底生成稳定哈希
            raw_input_json=raw,
        )

    def has_tool_calls(self, text: str) -> bool:
        """快速检查文本是否包含可能的工具调用"""
        return ('"tool"' in text and '"params"' in text) or \
               ('"name"' in text and '"parameters"' in text)


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