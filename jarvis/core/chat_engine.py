# jarvis/core/chat_engine.py
"""对话引擎 - 核心业务逻辑"""
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Any
from jarvis.core.entities import Message, Conversation, Step
from jarvis.core.memory_store import memory_store
from jarvis.core.task_engine import TaskExecutor
from jarvis.core.tool_parser import ToolCallParser, ToolCall
from jarvis.core.tool_result_formatter import ToolResultFormatter
from jarvis.core.tool_registry import tool_registry
from jarvis.services.ai import AIRouter, AIConfig, ProviderRegistry
from jarvis.services.ai.providers import OllamaAdapter, OpenAIAdapter, AnthropicAdapter
from jarvis.services.ai.models import Provider
from jarvis.utils.logger import get_logger

logger = get_logger(__name__)

# 最大工具调用迭代次数，防止无限循环
MAX_TOOL_ITERATIONS = 5


@dataclass
class SystemPromptSettings:
    """系统 Prompt 设置"""
    persona: str = ""      # 角色设定
    abilities: str = ""    # 能力说明
    memory: str = ""       # 记忆说明
    tools: str = ""        # 工具说明（额外补充）
    work_folder: str = ""  # 工作目录


class ChatEngine:
    """对话引擎 - 管理对话上下文和 LLM 调用"""

    def __init__(self):
        # Register providers
        ProviderRegistry.register(Provider.OLLAMA, OllamaAdapter)
        ProviderRegistry.register(Provider.OPENAI, OpenAIAdapter)
        ProviderRegistry.register(Provider.ANTHROPIC, AnthropicAdapter)
        ProviderRegistry.register(Provider.MINIMAX, AnthropicAdapter)

        # Initialize AI config
        self.ai_config = AIConfig()
        self.router = AIRouter(self.ai_config)
        self.memory = memory_store
        self.current_conversation: Optional[Conversation] = None
        self.work_folder: str = str(Path.cwd())

        # 工具执行器
        self.task_executor = TaskExecutor(self.work_folder)
        self.tool_parser = ToolCallParser(self.work_folder)

    def _build_system_prompt(self, settings: SystemPromptSettings = None) -> str:
        """构建系统提示词"""
        parts = []

        # 1. 角色设定
        if settings and settings.persona:
            parts.append(f"## 角色设定\n{settings.persona}")

        # 2. 工具描述（固定从 tool_registry 获取）
        parts.append(tool_registry.build_schema_for_llm())

        # 3. 额外工具说明
        if settings and settings.tools:
            parts.append(f"## 额外工具说明\n{settings.tools}")

        # 4. 能力说明
        if settings and settings.abilities:
            parts.append(f"## 能力说明\n{settings.abilities}")

        # 5. 记忆说明
        if settings and settings.memory:
            parts.append(f"## 记忆说明\n{settings.memory}")

        # 6. 工作目录（优先使用设置中的，否则使用实例的）
        work_folder = settings.work_folder if settings and settings.work_folder else self.work_folder
        parts.append(f"## 工作目录\n当前工作目录: {work_folder}")
        parts.append("""## 工具调用格式
当需要执行操作时，请以 JSON 格式返回工具调用：

单个调用（标准格式）：
```json
{"tool": "file", "params": {"action": "read", "path": "file.txt"}}
```

单个调用（MiniMax格式）：
```json
{"name": "bash", "parameters": {"command": "ls -la"}}
```

多个调用：
```json
[
  {"tool": "file", "params": {"action": "read", "path": "file.txt"}},
  {"tool": "bash", "params": {"command": "ls"}}
]
```

请用中文回答，保持简洁、专业且有帮助。如果需要执行操作，请在回复末尾以 JSON 格式明确说明将使用的工具。""")

        return "\n\n".join(parts)

    async def _load_prompt_settings(self) -> SystemPromptSettings:
        """从存储加载 Prompt 设置"""
        try:
            all_settings = await memory_store.get_all_settings()
            work_folder = all_settings.get("work_folder", "")
            return SystemPromptSettings(
                persona=all_settings.get("persona_prompt", ""),
                abilities=all_settings.get("abilities_prompt", ""),
                memory=all_settings.get("memory_prompt", ""),
                tools=all_settings.get("tools_prompt", ""),
                work_folder=work_folder
            )
        except Exception as e:
            logger.warning(f"Failed to load prompt settings: {e}")
            return SystemPromptSettings()

    def _extract_tool_calls_from_blocks(self, content_blocks: list) -> list:
        """从 Anthropic content_blocks 中提取工具调用"""
        tool_calls = []
        for block in content_blocks:
            if block.get("type") == "tool_use":
                tool_name = block.get("name", "")
                input_data = block.get("input", {})

                # 验证工具名
                if not tool_name or tool_name not in tool_registry.get_tool_names():
                    logger.warning(f"[ChatEngine] 未知工具: {tool_name}")
                    continue

                # 提取参数
                params = input_data.copy()
                action = params.pop("action", "")

                tool_call = ToolCall(
                    tool=tool_name,
                    action=action,
                    params=params,
                    raw=block.get("id", json.dumps(block))  # 优先使用 id
                )
                tool_calls.append(tool_call)
                logger.debug(f"[ChatEngine] 从 block 提取工具调用: {tool_name}.{action}")

        return tool_calls

    async def chat(
        self,
        user_input: str,
        conversation_id: Optional[str] = None,
        model: Optional[str] = None,
        stream: bool = False  # Default to non-stream for simpler response
    ) -> str:
        """处理对话 - 支持工具调用"""
        logger.info(f"[Chat] 开始处理对话 | conv_id={conversation_id} | model={model} | input_len={len(user_input)}")
        logger.debug(f"[Chat] 用户输入: {user_input[:100]}...")

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
                logger.info(f"[Chat] 从DB加载对话 | conv_id={conversation_id} | 消息数={len(conv_data.get('messages', []))}")
            else:
                logger.info(f"[Chat] 对话不存在，创建新对话 | conv_id={conversation_id}")
                self.current_conversation = Conversation(conversation_id=conversation_id)
        else:
            logger.info("[Chat] 无conv_id，创建新对话")
            self.current_conversation = Conversation()

        # 2. 添加用户消息
        self.current_conversation.add_message("user", user_input)
        logger.debug(f"[Chat] 用户消息已添加 | total_messages={len(self.current_conversation.messages)}")

        # 3. 检索相关记忆
        memories = await self.memory.retrieve(user_input, top_k=3)
        context_prompt = ""
        if memories:
            context_prompt = "\n相关记忆：\n" + "\n".join(
                [f"- {m['content']}" for m in memories]
            )
            logger.info(f"[Chat] 检索到 {len(memories)} 条相关记忆")
            for m in memories:
                logger.debug(f"[Chat] 记忆: {m['content'][:50]}...")
        else:
            logger.debug("[Chat] 未检索到相关记忆")

        # 4. 加载 Prompt 设置
        prompt_settings = await self._load_prompt_settings()
        if prompt_settings.persona or prompt_settings.abilities or prompt_settings.memory or prompt_settings.tools:
            logger.info(f"[Chat] 已加载 Prompt 设置 | persona={'有' if prompt_settings.persona else '无'} | abilities={'有' if prompt_settings.abilities else '无'} | memory={'有' if prompt_settings.memory else '无'} | tools={'有' if prompt_settings.tools else '无'}")
        else:
            logger.debug("[Chat] 未配置自定义 Prompt 设置")

        # 5. 构建系统 Prompt（包含记忆）
        system_prompt = self._build_system_prompt(prompt_settings)
        if context_prompt:
            system_prompt = system_prompt + context_prompt

        # 6. 构建消息历史
        messages = [
            {"role": "system", "content": system_prompt}
        ]
        for msg in self.current_conversation.get_history(limit=10):
            messages.append({"role": msg.role, "content": msg.content})
        logger.debug(f"[Chat] 构建消息历史 | history_count={len(self.current_conversation.get_history(limit=10))} | system_prompt_len={len(messages[0]['content'])}")

        # 7. 工具调用迭代循环
        final_response = ""
        iteration_count = 0

        for iteration_count in range(MAX_TOOL_ITERATIONS):
            logger.debug(f"[Chat] 第 {iteration_count + 1} 次迭代，调用 LLM...")
            # 调用 LLM
            response = await self.router.chat(
                messages,
                model=model,
                stream=False
            )

            response_text = response.content
            final_response = response_text

            # 检查是否有工具调用（检查 content 或 content_blocks 中的 tool_use）
            has_tools = self.tool_parser.has_tool_calls(response_text)
            if response.content_blocks:
                for block in response.content_blocks:
                    if block.get("type") == "tool_use":
                        has_tools = True
                        logger.debug(f"[Chat] 在 content_blocks 中发现 tool_use block: {block.get('name', 'unknown')}")
                        break

            logger.info(f"[Chat] LLM 响应 | len={len(response_text)} | has_tool_calls={has_tools}")
            logger.debug(f"[Chat] LLM 响应内容: {response_text[:200]}...")

            # 检查是否有工具调用
            if not has_tools:
                logger.debug("[Chat] 无工具调用，结束迭代")
                # 没有工具调用，返回响应
                break

            tool_calls = self.tool_parser.parse(response_text)
            if not tool_calls:
                # 解析失败但有工具标记，跳出
                logger.warning("[Chat] 检测到工具调用但解析失败")
                break

            logger.info(f"[Chat] 迭代 {iteration_count + 1}: 发现 {len(tool_calls)} 个工具调用")
            for tc in tool_calls:
                logger.info(f"[Chat] 工具调用: {tc.tool}.{tc.action} | params={tc.params}")

            # 7. 顺序执行工具调用
            for tool_call in tool_calls:
                step = Step(
                    tool=tool_call.tool,
                    params=tool_call.params
                )

                # 将工具调用作为独立消息记录（role: tool）
                tool_call_message = {
                    "tool": tool_call.tool,
                    "action": tool_call.action,
                    "params": tool_call.params,
                    "raw": tool_call.raw
                }
                self.current_conversation.add_message("tool", json.dumps(tool_call_message))

                try:
                    logger.debug(f"[Chat] 执行工具: {tool_call.tool}.{tool_call.action}")
                    result = await self.task_executor.execute_step(step)
                    status = result.get("status") if isinstance(result, dict) else "success"
                    logger.info(f"[Chat] 工具 {tool_call.tool}.{tool_call.action} 执行完成 | status={status}")
                    if isinstance(result, dict) and 'content' in result:
                        logger.debug(f"[Chat] 工具结果内容: {str(result['content'])[:100]}...")
                except Exception as e:
                    logger.error(f"[Chat] 工具执行错误: {tool_call.tool}.{tool_call.action} | error={e}")
                    result = {"status": "error", "message": str(e)}

                # 格式化结果并添加到消息 - 使用 Anthropic tool_result 格式
                result_message = ToolResultFormatter.format(
                    tool=tool_call.tool,
                    action=tool_call.action,
                    params=tool_call.params,
                    result=result,
                    tool_use_id=tool_call.raw  # 暂用 raw 作为 id
                )
                self.current_conversation.add_message("user", result_message["content"])
                # 添加到 LLM 消息历史 - 使用正确的 tool_result 格式
                messages.append({"role": "user", "content": result_message})

            # 检查后续响应是否也有工具调用
            has_tools = self.tool_parser.has_tool_calls(response_text)
            if response.content_blocks:
                for block in response.content_blocks:
                    if block.get("type") == "tool_use":
                        has_tools = True
                        logger.debug(f"[Chat] 后续响应中发现 tool_use block")
                        break

        # 8. 添加助手消息（最终响应）
        self.current_conversation.add_message("assistant", final_response)
        logger.info(f"[Chat] 对话完成 | total_messages={len(self.current_conversation.messages)}")

        # 9. 保存对话历史到 DB
        save_result = await self.memory.save_conversation(
            self.current_conversation.conversation_id,
            self.current_conversation.user_id,
            [msg.to_dict() for msg in self.current_conversation.messages],
            self.current_conversation.context
        )
        logger.info(f"[Chat] 对话已保存 | conv_id={self.current_conversation.conversation_id} | success={save_result}")

        # 10. 保存对话到 JSON 文件
        await self._save_conversation_to_file()

        # 11. 保存相关记忆（如果是有意义的信息）
        if len(user_input) > 10 and "记住" in user_input:
            key = user_input[:50].strip()
            save_mem_result = await self.memory.save(key, user_input)
            logger.info(f"[Chat] 保存记忆 | key={key} | success={save_mem_result}")

        if iteration_count >= MAX_TOOL_ITERATIONS - 1:
            logger.warning(f"[Chat] 达到最大工具迭代次数 ({MAX_TOOL_ITERATIONS})")

        return final_response

    async def stream_chat(
        self,
        user_input: str,
        conversation_id: Optional[str] = None,
        model: Optional[str] = None,
        user_id: Optional[str] = None
    ):
        """流式对话 - 两阶段：第一阶段执行工具，第二阶段流式返回"""
        logger.info(f"[StreamChat] 开始处理 | conv_id={conversation_id} | user_id={user_id} | model={model} | input_len={len(user_input)}")

        # 1. 获取或创建对话上下文
        if conversation_id:
            conv_data = await self.memory.get_conversation(conversation_id)
            if conv_data:
                self.current_conversation = Conversation(
                    conversation_id=conversation_id,
                    user_id=conv_data.get("user_id", "") or user_id or "",
                    messages=[Message(**m) for m in conv_data.get("messages", [])],
                    context=conv_data.get("context", {})
                )
                logger.info(f"[StreamChat] 从DB加载对话 | conv_id={conversation_id} | 消息数={len(conv_data.get('messages', []))}")
            else:
                logger.info(f"[StreamChat] 对话不存在，创建新对话 | conv_id={conversation_id}")
                self.current_conversation = Conversation(conversation_id=conversation_id, user_id=user_id or "")
        else:
            logger.info("[StreamChat] 无conv_id，创建新对话")
            self.current_conversation = Conversation(user_id=user_id or "")

        # 2. 添加用户消息
        self.current_conversation.add_message("user", user_input)
        logger.debug(f"[StreamChat] 用户消息已添加 | total_messages={len(self.current_conversation.messages)}")

        # 3. 加载 Prompt 设置
        prompt_settings = await self._load_prompt_settings()
        logger.debug(f"[StreamChat] Prompt设置已加载 | persona={'有' if prompt_settings.persona else '无'}")

        # 4. 构建消息列表
        messages = [
            {"role": "system", "content": self._build_system_prompt(prompt_settings)}
        ]
        if self.current_conversation.messages:
            messages.extend([
                {"role": m.role, "content": m.content}
                for m in self.current_conversation.get_history(limit=10)
            ])
        logger.debug(f"[StreamChat] 构建消息 | history_count={len(self.current_conversation.get_history(limit=10))}")

        messages.append({"role": "user", "content": user_input})

        # 5. 第一阶段：非流式调用以检测工具
        logger.debug("[StreamChat] 调用 LLM (第一阶段)...")
        response = await self.router.chat(messages, model=model, stream=False)
        response_text = response.content
        logger.info(f"[StreamChat] LLM 第一阶段响应 | len={len(response_text)}")

        # 6. 检测并执行工具调用
        iteration_count = 0
        final_response = response_text

        # 检查是否有工具调用（检查 content 或 content_blocks 中的 tool_use）
        has_tools = self.tool_parser.has_tool_calls(response_text)
        if response.content_blocks:
            for block in response.content_blocks:
                if block.get("type") == "tool_use":
                    has_tools = True
                    logger.debug(f"[StreamChat] 在 content_blocks 中发现 tool_use block: {block.get('name', 'unknown')}")
                    break

        for iteration_count in range(MAX_TOOL_ITERATIONS):
            if not has_tools:
                logger.debug("[StreamChat] 无工具调用，结束迭代")
                break

            tool_calls = self.tool_parser.parse(response_text)

            # 如果文本解析失败但有 content_blocks，尝试从 content_blocks 提取
            if not tool_calls and response.content_blocks:
                tool_calls = self._extract_tool_calls_from_blocks(response.content_blocks)
                logger.debug(f"[StreamChat] 从 content_blocks 提取到 {len(tool_calls)} 个工具调用")

            if not tool_calls:
                break

            logger.info(f"[StreamChat] 第 {iteration_count + 1} 次迭代: 发现 {len(tool_calls)} 个工具调用")
            for tc in tool_calls:
                logger.info(f"[StreamChat] 工具调用: {tc.tool}.{tc.action} | params={tc.params}")

            # 将助手响应添加到消息历史
            assistant_content = response.content_blocks if response.content_blocks else response.content
            messages.append({
                "role": "assistant",
                "content": assistant_content
            })

            # 执行工具
            for tool_call in tool_calls:
                step = Step(tool=tool_call.tool, params=tool_call.params)

                # 将工具调用作为独立消息记录（role: tool）
                tool_call_message = {
                    "tool": tool_call.tool,
                    "action": tool_call.action,
                    "params": tool_call.params,
                    "raw": tool_call.raw
                }
                self.current_conversation.add_message("tool", json.dumps(tool_call_message))

                try:
                    logger.debug(f"[StreamChat] 执行工具: {tool_call.tool}.{tool_call.action}")
                    result = await self.task_executor.execute_step(step)
                    status = result.get("status") if isinstance(result, dict) else "success"
                    logger.info(f"[StreamChat] 工具 {tool_call.tool}.{tool_call.action} 执行完成 | status={status}")
                except Exception as e:
                    logger.error(f"[StreamChat] 工具执行错误: {tool_call.tool}.{tool_call.action} | error={e}")
                    result = {"status": "error", "message": str(e)}

                # 格式化结果并添加 - 使用 Anthropic tool_result 格式
                result_message = ToolResultFormatter.format(
                    tool=tool_call.tool,
                    action=tool_call.action,
                    params=tool_call.params,
                    result=result,
                    tool_use_id=tool_call.raw
                )
                self.current_conversation.add_message("user", result_message["content"])
                messages.append({"role": "user", "content": result_message})

            # 再次调用 LLM 获取响应
            logger.debug(f"[StreamChat] 再次调用 LLM (迭代 {iteration_count + 1})...")
            response = await self.router.chat(messages, model=model, stream=False)
            response_text = response.content
            final_response = response_text
            logger.info(f"[StreamChat] LLM 后续响应 | len={len(response_text)}")

            # 检查后续响应是否也有工具调用
            has_tools = self.tool_parser.has_tool_calls(response_text)
            if response.content_blocks:
                for block in response.content_blocks:
                    if block.get("type") == "tool_use":
                        has_tools = True
                        logger.debug(f"[StreamChat] 后续响应中发现 tool_use block")
                        break

        # 7. 保存对话历史
        self.current_conversation.add_message("assistant", final_response)
        save_result = await self.memory.save_conversation(
            self.current_conversation.conversation_id,
            self.current_conversation.user_id,
            [msg.to_dict() for msg in self.current_conversation.messages],
            self.current_conversation.context
        )
        logger.info(f"[StreamChat] 对话已保存 | conv_id={self.current_conversation.conversation_id} | success={save_result}")

        # 8. 保存对话到 JSON 文件
        await self._save_conversation_to_file()

        # 9. 流式返回最终响应
        logger.info(f"[StreamChat] 开始流式返回 | response_len={len(final_response)}")
        for token in final_response:
            yield token
        logger.info("[StreamChat] 流式返回完成")

    async def stream_chat_with_messages(
        self,
        user_input: str,
        messages_history: list[dict],
        model: Optional[str] = None,
        conversation_id: Optional[str] = None,
        user_id: Optional[str] = None
    ):
        """流式对话 - 使用传入的完整消息历史"""
        logger.info(f"[StreamChatWithMsgs] 开始处理 | conv_id={conversation_id} | user_id={user_id} | model={model} | input_len={len(user_input)} | history_len={len(messages_history)}")

        # 1. 获取或创建对话上下文
        if conversation_id:
            conv_data = await self.memory.get_conversation(conversation_id)
            if conv_data:
                self.current_conversation = Conversation(
                    conversation_id=conversation_id,
                    user_id=conv_data.get("user_id", "") or user_id or "",
                    messages=[Message(**m) for m in conv_data.get("messages", [])],
                    context=conv_data.get("context", {})
                )
                logger.info(f"[StreamChatWithMsgs] 从DB加载对话 | conv_id={conversation_id} | 消息数={len(conv_data.get('messages', []))}")
            else:
                logger.info(f"[StreamChatWithMsgs] 对话不存在，创建新对话 | conv_id={conversation_id}")
                self.current_conversation = Conversation(conversation_id=conversation_id, user_id=user_id or "")
        else:
            logger.info("[StreamChatWithMsgs] 无conv_id，创建新对话")
            self.current_conversation = Conversation(user_id=user_id or "")
            logger.debug("[StreamChatWithMsgs] 新建空对话上下文")

        # 2. 添加用户消息
        self.current_conversation.add_message("user", user_input)
        logger.debug(f"[StreamChatWithMsgs] 用户消息已添加 | total_messages={len(self.current_conversation.messages)}")

        # 3. 加载 Prompt 设置
        prompt_settings = await self._load_prompt_settings()
        logger.debug(f"[StreamChatWithMsgs] Prompt设置已加载")

        # 4. 构建消息列表 - 使用传入的历史
        messages = [
            {"role": "system", "content": self._build_system_prompt(prompt_settings)}
        ]

        # 添加历史消息（过滤掉 system）
        history_count = 0
        for msg in messages_history:
            if msg.get("role") != "system":
                messages.append({"role": msg["role"], "content": msg["content"]})
                history_count += 1
        logger.debug(f"[StreamChatWithMsgs] 已添加 {history_count} 条历史消息")

        # 添加当前用户消息
        messages.append({"role": "user", "content": user_input})

        # 5. 第一阶段：非流式调用以检测工具
        logger.debug("[StreamChatWithMsgs] 调用 LLM (第一阶段)...")
        response = await self.router.chat(messages, model=model, stream=False)
        response_text = response.content
        logger.info(f"[StreamChatWithMsgs] LLM 第一阶段响应 | len={len(response_text)}")

        # 6. 检测并执行工具调用
        iteration_count = 0
        final_response = response_text

        # 检查是否有工具调用（检查 content 或 content_blocks 中的 tool_use）
        has_tools = self.tool_parser.has_tool_calls(response_text)
        if response.content_blocks:
            for block in response.content_blocks:
                if block.get("type") == "tool_use":
                    has_tools = True
                    logger.debug(f"[StreamChatWithMsgs] 在 content_blocks 中发现 tool_use block: {block.get('name', 'unknown')}")
                    break

        for iteration_count in range(MAX_TOOL_ITERATIONS):
            if not has_tools:
                logger.debug("[StreamChatWithMsgs] 无工具调用，结束迭代")
                break

            # 从响应文本或 content_blocks 解析工具调用
            tool_calls = self.tool_parser.parse(response_text)

            # 如果文本解析失败但有 content_blocks，尝试从 content_blocks 提取
            if not tool_calls and response.content_blocks:
                tool_calls = self._extract_tool_calls_from_blocks(response.content_blocks)
                logger.debug(f"[StreamChatWithMsgs] 从 content_blocks 提取到 {len(tool_calls)} 个工具调用")

            if not tool_calls:
                break

            logger.info(f"[StreamChatWithMsgs] 第 {iteration_count + 1} 次迭代: 发现 {len(tool_calls)} 个工具调用")
            for tc in tool_calls:
                logger.info(f"[StreamChatWithMsgs] 工具调用: {tc.tool}.{tc.action} | params={tc.params}")

            # 将助手的完整响应添加到消息历史（包含 tool_use blocks）
            # 使用 content_blocks 格式（Anthropic API 返回的结构）
            assistant_content = response.content_blocks if response.content_blocks else response.content
            messages.append({
                "role": "assistant",
                "content": assistant_content
            })

            # 执行工具
            for tool_call in tool_calls:
                step = Step(tool=tool_call.tool, params=tool_call.params)

                # 将工具调用作为独立消息记录（role: tool）
                tool_call_message = {
                    "tool": tool_call.tool,
                    "action": tool_call.action,
                    "params": tool_call.params,
                    "raw": tool_call.raw
                }
                self.current_conversation.add_message("tool", json.dumps(tool_call_message))

                try:
                    logger.debug(f"[StreamChatWithMsgs] 执行工具: {tool_call.tool}.{tool_call.action}")
                    result = await self.task_executor.execute_step(step)
                    status = result.get("status") if isinstance(result, dict) else "success"
                    logger.info(f"[StreamChatWithMsgs] 工具 {tool_call.tool}.{tool_call.action} 执行完成 | status={status}")
                except Exception as e:
                    logger.error(f"[StreamChatWithMsgs] 工具执行错误: {tool_call.tool}.{tool_call.action} | error={e}")
                    result = {"status": "error", "message": str(e)}

                # 格式化结果并添加 - 使用 Anthropic tool_result 格式
                result_message = ToolResultFormatter.format(
                    tool=tool_call.tool,
                    action=tool_call.action,
                    params=tool_call.params,
                    result=result,
                    tool_use_id=tool_call.raw
                )
                self.current_conversation.add_message("user", result_message["content"])
                messages.append({"role": "user", "content": result_message})

            # 再次调用 LLM 获取响应
            logger.debug(f"[StreamChatWithMsgs] 再次调用 LLM (迭代 {iteration_count + 1})...")
            response = await self.router.chat(messages, model=model, stream=False)
            response_text = response.content
            final_response = response_text
            logger.info(f"[StreamChatWithMsgs] LLM 后续响应 | len={len(response_text)}")

            # 检查后续响应是否也有工具调用
            has_tools = self.tool_parser.has_tool_calls(response_text)
            if response.content_blocks:
                for block in response.content_blocks:
                    if block.get("type") == "tool_use":
                        has_tools = True
                        logger.debug(f"[StreamChatWithMsgs] 后续响应中发现 tool_use block")
                        break

        # 7. 保存对话历史
        self.current_conversation.add_message("assistant", final_response)
        save_result = await self.memory.save_conversation(
            self.current_conversation.conversation_id,
            self.current_conversation.user_id,
            [msg.to_dict() for msg in self.current_conversation.messages],
            self.current_conversation.context
        )
        logger.info(f"[StreamChatWithMsgs] 对话已保存 | conv_id={self.current_conversation.conversation_id} | success={save_result}")

        # 8. 保存对话到 JSON 文件
        await self._save_conversation_to_file()

        # 9. 流式返回最终响应
        logger.info(f"[StreamChatWithMsgs] 开始流式返回 | response_len={len(final_response)}")
        for token in final_response:
            yield token
        logger.info("[StreamChatWithMsgs] 流式返回完成")

    async def _save_conversation_to_file(self):
        """将会话保存为 JSON 文件到工作目录"""
        try:
            if not self.current_conversation:
                return

            conv = self.current_conversation

            # 确保目录存在
            conv_dir = Path(self.work_folder) / "conversations"
            conv_dir.mkdir(parents=True, exist_ok=True)

            # 文件名格式: {conversation_id}.json
            file_path = conv_dir / f"{conv.conversation_id}.json"

            # 构建系统 Prompt
            prompt_settings = await self._load_prompt_settings()
            system_prompt = self._build_system_prompt(prompt_settings)

            # Helper to format timestamp
            def format_timestamp(ts):
                if ts is None:
                    return None
                if isinstance(ts, str):
                    return ts
                return ts.isoformat()

            # 准备数据
            data = {
                "conversation_id": conv.conversation_id,
                "user_id": conv.user_id,
                "system_prompt": system_prompt,
                "messages": [msg.to_dict() for msg in conv.messages],
                "context": conv.context,
                "created_at": format_timestamp(conv.created_at),
                "updated_at": format_timestamp(conv.updated_at)
            }

            # 写入文件
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            logger.info(f"[Chat] 对话已保存到文件 | path={file_path}")
        except Exception as e:
            logger.error(f"[Chat] 保存对话到文件失败: {e}")

    async def list_models(self, force_refresh: bool = False) -> list[dict]:
        """List available models from all providers"""
        logger.info(f"[ChatEngine] 列出可用模型 | force_refresh={force_refresh}")
        models = await self.router.list_models(force_refresh=force_refresh)
        logger.info(f"[ChatEngine] 可用模型数量: {len(models)}")
        return models

    def to_dict(self) -> dict:
        """导出状态"""
        return {
            "current_conversation": {
                "conversation_id": self.current_conversation.conversation_id if self.current_conversation else None,
                "messages_count": len(self.current_conversation.messages) if self.current_conversation else 0
            }
        }