# jarvis/core/chat_engine.py
"""对话引擎 - 核心业务逻辑"""
from pathlib import Path
from typing import Optional, Any
from jarvis.core.entities import Message, Conversation, Step
from jarvis.core.memory_store import memory_store
from jarvis.core.task_engine import TaskExecutor
from jarvis.core.tool_parser import ToolCallParser
from jarvis.core.tool_result_formatter import ToolResultFormatter
from jarvis.services.ai import AIRouter, AIConfig, ProviderRegistry
from jarvis.services.ai.providers import OllamaAdapter, OpenAIAdapter, AnthropicAdapter
from jarvis.services.ai.models import Provider
from jarvis.utils.logger import get_logger

logger = get_logger(__name__)

# 最大工具调用迭代次数，防止无限循环
MAX_TOOL_ITERATIONS = 5


class ChatEngine:
    """对话引擎 - 管理对话上下文和 LLM 调用"""

    def __init__(self):
        # Register providers
        ProviderRegistry.register(Provider.OLLAMA, OllamaAdapter)
        ProviderRegistry.register(Provider.OPENAI, OpenAIAdapter)
        ProviderRegistry.register(Provider.ANTHROPIC, AnthropicAdapter)

        # Initialize AI config
        self.ai_config = AIConfig()
        self.router = AIRouter(self.ai_config)
        self.memory = memory_store
        self.current_conversation: Optional[Conversation] = None
        self.work_folder: str = str(Path.cwd())

        # 工具执行器
        self.task_executor = TaskExecutor(self.work_folder)
        self.tool_parser = ToolCallParser(self.work_folder)

        # 工具列表定义
        self.available_tools = """## 可用工具

### 1. 文件操作 (tool: file)
执行文件读写编辑删除等操作。

| 操作 | 参数 | 说明 |
|------|------|------|
| read | path | 读取文件内容 |
| write | path, content | 写入文件 |
| edit | path, old_content, new_content | 修改文件 |
| delete | path | 删除文件/目录 |
| list | path | 列出目录文件 |
| mkdir | path | 创建目录 |
| exists | path | 检查文件是否存在 |
| set_work_folder | folder | 设置工作目录 |
| get_work_folder | - | 获取当前工作目录 |

### 2. 浏览器自动化 (tool: browser)
使用 Playwright 执行浏览器操作。

### 3. 桌面控制 (tool: desktop)
使用 pyautogui 执行桌面自动化操作。

### 4. API 调用 (tool: api)
发送 HTTP 请求。

### 5. 通用工具 (tool: tool)
运行 MCP 工具。

### 6. Bash 命令 (tool: bash)
执行 Linux/Mac 系统命令。

| 参数 | 说明 |
|------|------|
| command | 要执行的命令 |
| timeout | 超时时间（秒），默认 30 |
| cwd | 工作目录 |

**高危命令禁止执行**: rm -rf, dd, mkfs, wget/curl 管道执行, chmod 777, chown, shutdown, reboot, kill -9 等

## 工具调用格式
当需要执行操作时，请以 JSON 格式返回工具调用：

单个调用：
```json
{"tool": "file", "params": {"action": "read", "path": "file.txt"}}
```

多个调用：
```json
[
  {"tool": "file", "params": {"action": "read", "path": "file.txt"}},
  {"tool": "browser", "params": {"action": "navigate", "url": "https://example.com"}}
]
```

## 工作目录
当前工作目录: {work_folder}

请用中文回答，保持简洁、专业且有帮助。如果需要执行操作，请在回复末尾以 JSON 格式明确说明将使用的工具。"""

    def _build_system_prompt(self) -> str:
        """构建系统提示词"""
        return self.available_tools.replace("{work_folder}", self.work_folder)

    async def chat(
        self,
        user_input: str,
        conversation_id: Optional[str] = None,
        model: Optional[str] = None,
        stream: bool = False  # Default to non-stream for simpler response
    ) -> str:
        """处理对话 - 支持工具调用"""
        # 1. 获取或创建对话上下文
        if conversation_id:
            conv_data = await self.memory.get_conversation(conversation_id)
            if conv_data:
                self.current_conversation = Conversation(
                    conversation_id=conversation_id,
                    user_id=conv_data.get("user_id", ""),
                    messages=[Message(**m) for m in conv_data.get("messages", [])],
                    context=conv_data.get("context", {})
                )
            else:
                self.current_conversation = Conversation(conversation_id=conversation_id)
        else:
            self.current_conversation = Conversation()

        # 2. 添加用户消息
        self.current_conversation.add_message("user", user_input)

        # 3. 检索相关记忆
        memories = await self.memory.retrieve(user_input, top_k=3)
        context_prompt = ""
        if memories:
            context_prompt = "\n相关记忆：\n" + "\n".join(
                [f"- {m['content']}" for m in memories]
            )

        # 4. 构建消息历史
        messages = [
            {"role": "system", "content": self._build_system_prompt() + context_prompt}
        ]
        for msg in self.current_conversation.get_history(limit=10):
            messages.append({"role": msg.role, "content": msg.content})

        # 5. 工具调用迭代循环
        final_response = ""
        iteration_count = 0

        for iteration_count in range(MAX_TOOL_ITERATIONS):
            # 调用 LLM
            response = await self.router.chat(
                messages,
                model=model,
                stream=False
            )

            response_text = response.content
            final_response = response_text

            # 检查是否有工具调用
            if not self.tool_parser.has_tool_calls(response_text):
                # 没有工具调用，返回响应
                break

            tool_calls = self.tool_parser.parse(response_text)
            if not tool_calls:
                # 解析失败但有工具标记，跳出
                break

            logger.info(f"迭代 {iteration_count + 1}: 发现 {len(tool_calls)} 个工具调用")

            # 6. 顺序执行工具调用
            for tool_call in tool_calls:
                step = Step(
                    tool=tool_call.tool,
                    params=tool_call.params
                )
                try:
                    result = await self.task_executor.execute_step(step)
                    status = result.get("status") if isinstance(result, dict) else "success"
                    logger.info(f"工具 {tool_call.tool}.{tool_call.action} 执行完成: {status}")
                except Exception as e:
                    logger.error(f"工具执行错误: {e}")
                    result = {"status": "error", "message": str(e)}

                # 格式化结果并添加到消息
                result_message = ToolResultFormatter.format(
                    tool=tool_call.tool,
                    action=tool_call.action,
                    params=tool_call.params,
                    result=result
                )
                self.current_conversation.add_message("user", result_message)
                messages.append({"role": "user", "content": result_message})

        # 7. 添加助手消息（最终响应）
        self.current_conversation.add_message("assistant", final_response)

        # 8. 保存对话历史
        await self.memory.save_conversation(
            self.current_conversation.conversation_id,
            self.current_conversation.user_id,
            [msg.to_dict() for msg in self.current_conversation.messages],
            self.current_conversation.context
        )

        # 9. 保存相关记忆（如果是有意义的信息）
        if len(user_input) > 10 and "记住" in user_input:
            key = user_input[:50].strip()
            await self.memory.save(key, user_input)

        if iteration_count >= MAX_TOOL_ITERATIONS - 1:
            logger.warning(f"已达到最大工具迭代次数 ({MAX_TOOL_ITERATIONS})")

        return final_response

    async def stream_chat(
        self,
        user_input: str,
        conversation_id: Optional[str] = None,
        model: Optional[str] = None
    ):
        """流式对话 - 两阶段：第一阶段执行工具，第二阶段流式返回"""
        # 1. 获取或创建对话上下文
        if conversation_id:
            conv_data = await self.memory.get_conversation(conversation_id)
            if conv_data:
                self.current_conversation = Conversation(
                    conversation_id=conversation_id,
                    user_id=conv_data.get("user_id", ""),
                    messages=[Message(**m) for m in conv_data.get("messages", [])],
                    context=conv_data.get("context", {})
                )
            else:
                self.current_conversation = Conversation(conversation_id=conversation_id)
        else:
            self.current_conversation = Conversation()

        # 2. 添加用户消息
        self.current_conversation.add_message("user", user_input)

        # 3. 构建消息列表
        messages = [
            {"role": "system", "content": self._build_system_prompt()}
        ]
        if self.current_conversation.messages:
            messages.extend([
                {"role": m.role, "content": m.content}
                for m in self.current_conversation.get_history(limit=10)
            ])

        messages.append({"role": "user", "content": user_input})

        # 4. 第一阶段：非流式调用以检测工具
        response = await self.router.chat(messages, model=model, stream=False)
        response_text = response.content

        # 5. 检测并执行工具调用
        iteration_count = 0
        final_response = response_text

        for iteration_count in range(MAX_TOOL_ITERATIONS):
            if not self.tool_parser.has_tool_calls(response_text):
                break

            tool_calls = self.tool_parser.parse(response_text)
            if not tool_calls:
                break

            logger.info(f"Stream: 发现 {len(tool_calls)} 个工具调用")

            # 执行工具
            for tool_call in tool_calls:
                step = Step(tool=tool_call.tool, params=tool_call.params)
                try:
                    result = await self.task_executor.execute_step(step)
                    status = result.get("status") if isinstance(result, dict) else "success"
                    logger.info(f"Stream: 工具 {tool_call.tool}.{tool_call.action} 执行完成: {status}")
                except Exception as e:
                    logger.error(f"Stream: 工具执行错误: {e}")
                    result = {"status": "error", "message": str(e)}

                # 格式化结果并添加
                result_message = ToolResultFormatter.format(
                    tool=tool_call.tool,
                    action=tool_call.action,
                    params=tool_call.params,
                    result=result
                )
                self.current_conversation.add_message("user", result_message)
                messages.append({"role": "user", "content": result_message})

            # 再次调用 LLM 获取响应
            response = await self.router.chat(messages, model=model, stream=False)
            response_text = response.content
            final_response = response_text

        # 6. 保存对话历史
        self.current_conversation.add_message("assistant", final_response)
        await self.memory.save_conversation(
            self.current_conversation.conversation_id,
            self.current_conversation.user_id,
            [msg.to_dict() for msg in self.current_conversation.messages],
            self.current_conversation.context
        )

        # 7. 流式返回最终响应
        for token in final_response:
            yield token

    def set_work_folder(self, folder: str):
        """设置工作目录"""
        self.work_folder = folder
        logger.info(f"Work folder set to: {folder}")

    async def list_models(self) -> list[dict]:
        """List available models from all providers"""
        return await self.router.list_models()

    def to_dict(self) -> dict:
        """导出状态"""
        return {
            "current_conversation": {
                "conversation_id": self.current_conversation.conversation_id if self.current_conversation else None,
                "messages_count": len(self.current_conversation.messages) if self.current_conversation else 0
            }
        }