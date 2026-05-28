# jarvis/services/ai/providers/anthropic_tools.py
"""将工具定义转换为 Anthropic API 的 tools 格式"""
from jarvis.core.tool_registry import tool_registry
from jarvis.utils.logger import get_logger

logger = get_logger(__name__)


def build_anthropic_tools() -> list[dict]:
    """构建 Anthropic API 格式的工具定义"""
    tools = []

    for tool_def in tool_registry.list_tools():
        # 转换参数为 Anthropic 格式
        input_schema = {
            "type": "object",
            "properties": {},
            "required": []
        }

        for param_name, param in tool_def.parameters.items():
            prop = {
                "type": param.type if param.type else "string",
                "description": param.description
            }
            if param.enum:
                prop["enum"] = param.enum
            if param.default is not None:
                prop["default"] = param.default

            input_schema["properties"][param_name] = prop
            if param.required:
                input_schema["required"].append(param_name)

        tools.append({
            "name": tool_def.name,
            "description": tool_def.description,
            "input_schema": input_schema
        })

    logger.debug(f"Built {len(tools)} tools for Anthropic API")
    return tools