# jarvis/core/tool_registry.py
"""工具注册表 - 统一管理工具定义和Schema"""
from dataclasses import dataclass, field
from typing import Optional, Any
from jarvis.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ToolParam:
    """工具参数定义"""
    name: str
    description: str
    type: str = "string"  # string, number, boolean, object, array
    required: bool = False
    default: Any = None
    enum: list[Any] = None


@dataclass
class ToolDefinition:
    """工具定义"""
    name: str  # tool name: file, bash, browser, etc.
    description: str
    category: str = ""
    parameters: dict[str, ToolParam] = field(default_factory=dict)
    # MiniMax format support
    minimax_name: str = ""  # Alternative name for MiniMax format
    minmax_params_key: str = "parameters"  # params or parameters


class ToolRegistry:
    """工具注册表"""

    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}
        self._register_builtin_tools()

    def _register_builtin_tools(self):
        """注册内置工具"""
        # File Tool
        self.register(ToolDefinition(
            name="file",
            description="文件读写编辑删除等操作。所有路径相对于工作目录，bare filename 自动解析到工作目录下。",
            category="文件操作",
            parameters={
                "action": ToolParam("action", "操作类型: read/write/edit/delete/list/mkdir/exists", required=True, enum=["read", "write", "edit", "delete", "list", "mkdir", "exists"]),
                "path": ToolParam("path", "文件路径（相对于工作目录）", required=True),
                "content": ToolParam("content", "文件内容（write/edit时使用）"),
                "old_content": ToolParam("old_content", "要修改的旧内容（edit时使用）"),
                "new_content": ToolParam("new_content", "新内容（edit时使用）"),
            }
        ))

        # Bash Tool
        self.register(ToolDefinition(
            name="bash",
            description="执行 Linux/Mac 系统命令。默认在工作目录下执行，可通过 cwd 参数指定其他目录。高危命令会被拦截。",
            category="系统命令",
            parameters={
                "command": ToolParam("command", "要执行的命令", required=True),
                "timeout": ToolParam("timeout", "超时时间（秒），默认30", type="number", default=30),
                "cwd": ToolParam("cwd", "工作目录（默认使用系统工作目录）"),
            }
        ))

        # Browser Tool
        self.register(ToolDefinition(
            name="browser",
            description="浏览器自动化操作（使用 Playwright）",
            category="浏览器",
            parameters={
                "action": ToolParam("action", "操作类型", required=True, enum=["navigate", "click", "type", "screenshot", "evaluate"]),
                "url": ToolParam("url", "URL地址（navigate时使用）"),
                "selector": ToolParam("selector", "元素选择器"),
                "text": ToolParam("text", "输入文本"),
                "script": ToolParam("script", "JavaScript脚本（evaluate时使用）"),
            }
        ))

        # Desktop Tool
        self.register(ToolDefinition(
            name="desktop",
            description="桌面自动化操作（使用 pyautogui）",
            category="桌面控制",
            parameters={
                "action": ToolParam("action", "操作类型", required=True, enum=["click", "double_click", "right_click", "move", "type", "press", "screenshot"]),
                "x": ToolParam("x", "X坐标"),
                "y": ToolParam("y", "Y坐标"),
                "text": ToolParam("text", "输入文本"),
                "key": ToolParam("key", "按键名称"),
            }
        ))

        # API Tool
        self.register(ToolDefinition(
            name="api",
            description="发送 HTTP 请求",
            category="网络",
            parameters={
                "method": ToolParam("method", "HTTP方法", type="string", enum=["GET", "POST", "PUT", "DELETE", "PATCH"], default="GET"),
                "url": ToolParam("url", "请求URL", required=True),
                "headers": ToolParam("headers", "请求头", type="object"),
                "body": ToolParam("body", "请求体", type="object"),
            }
        ))

        # Tool Runner
        self.register(ToolDefinition(
            name="tool",
            description="运行 MCP 工具",
            category="工具",
            parameters={
                "name": ToolParam("name", "工具名称", required=True),
                "params": ToolParam("params", "工具参数", type="object"),
            }
        ))

        # Subagent — 委派子任务到角色化子代理 (researcher/coder/reviewer/...)
        # 设计动机: 主对话上下文有限, 复杂调研/编码/复审交给隔离的子代理.
        # 编排器负责串行/并行/汇总, 主对话只看到结构化结果.
        self.register(ToolDefinition(
            name="subagent",
            description=(
                "委派子任务给角色化子代理 (隔离上下文, 可并行). "
                "roles: researcher(调研), coder(代码), reviewer(复审), "
                "summarizer(摘要), planner(规划), general(通用). "
                "mode: sequential(顺序, 下一任务可见上一步输出) | "
                "parallel(并行, 独立任务) | map_reduce(并行 + 汇总). "
                "适用于: 多源调研、对比方案、批量生成、代码+复审流水线等."
            ),
            category="子代理",
            parameters={
                "role": ToolParam(
                    "role", "子代理角色",
                    required=True,
                    enum=["researcher", "coder", "reviewer",
                          "summarizer", "planner", "general"],
                ),
                "task": ToolParam("task", "子任务描述", required=True),
                "context": ToolParam("context", "可选的背景上下文 (可让子代理看到主对话要点)", type="string"),
                "mode": ToolParam(
                    "mode", "编排模式 (仅 batch 调用时生效)",
                    enum=["sequential", "parallel", "map_reduce"],
                ),
                "tasks": ToolParam(
                    "tasks",
                    "批量子任务列表, 每项含 role/task/context",
                    type="array",
                ),
                "reduce_prompt": ToolParam(
                    "reduce_prompt",
                    "map_reduce 模式下让 LLM 综合所有子代理输出的指令",
                    type="string",
                ),
            }
        ))

    def register(self, tool: ToolDefinition):
        """注册工具"""
        self._tools[tool.name] = tool
        logger.info(f"Registered tool: {tool.name}")

    def get(self, name: str) -> Optional[ToolDefinition]:
        """获取工具定义"""
        return self._tools.get(name)

    def list_tools(self) -> list[ToolDefinition]:
        """列出所有工具"""
        return list(self._tools.values())

    def get_tool_names(self) -> list[str]:
        """获取所有工具名称"""
        return list(self._tools.keys())

    def build_schema_for_llm(self) -> str:
        """构建供 LLM 使用的工具描述"""
        lines = ["## 可用工具"]

        for tool in self._tools.values():
            lines.append(f"\n### {tool.category} (tool: {tool.name})")
            lines.append(tool.description)

            # 参数表格
            if tool.parameters:
                lines.append("\n| 参数 | 类型 | 必填 | 说明 |")
                lines.append("|------|------|------|------|")
                for param_name, param in tool.parameters.items():
                    required_str = "是" if param.required else "否"
                    type_str = param.type
                    enum_str = f" 可选值: {param.enum}" if param.enum else ""
                    default_str = f" 默认: {param.default}" if param.default is not None else ""
                    lines.append(f"| {param_name} | {type_str} | {required_str} | {param.description}{enum_str}{default_str} |")

        return "\n".join(lines)

    def build_json_schema(self) -> dict:
        """构建 JSON Schema 格式的工具定义（用于 MiniMax）"""
        properties = {}
        required = []

        for tool in self._tools.values():
            tool_props = {}
            tool_required = []

            for param_name, param in tool.parameters.items():
                prop = {
                    "type": param.type,
                    "description": param.description
                }
                if param.enum:
                    prop["enum"] = param.enum
                if param.default is not None:
                    prop["default"] = param.default

                tool_props[param_name] = prop
                if param.required:
                    tool_required.append(param_name)

            properties[tool.name] = {
                "type": "object",
                "properties": tool_props,
                "required": tool_required if tool_required else None
            }

        return {
            "type": "object",
            "properties": properties
        }


    def build_anthropic_tools(self) -> list[dict]:
        """构建 Anthropic-compatible 工具列表 (用于 /v1/messages)"""
        tools = []
        for tool in self._tools.values():
            props = {}
            required_params = []
            for pname, p in tool.parameters.items():
                prop = {"type": p.type, "description": p.description}
                if p.enum:
                    prop["enum"] = p.enum
                props[pname] = prop
                if p.required:
                    required_params.append(pname)
            tools.append({
                "name": tool.name,
                "description": tool.description,
                "input_schema": {
                    "type": "object",
                    "properties": props,
                    "required": required_params,
                },
            })
        return tools


# 全局工具注册表
tool_registry = ToolRegistry()