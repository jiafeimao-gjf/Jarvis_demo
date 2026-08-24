# jarvis/core/chat_engine.py
"""对话引擎 - 核心业务逻辑"""
from __future__ import annotations

import json
import base64
import re
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
from jarvis.services.ai.providers import OllamaAdapter, OpenAIAdapter, AnthropicAdapter, MiniMaxAdapter
from jarvis.services.ai.models import Provider
from jarvis.services.ai.instance_config import get_instance_store
from jarvis.services.skill_loader import load_skills, load_prompt_files
from jarvis.core.topic_generator import generate_topic
from jarvis.core.context_manager import ContextManager
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
        # Register providers — adapter per API format, model → provider from registry
        ProviderRegistry.register(Provider.OLLAMA, OllamaAdapter)
        ProviderRegistry.register(Provider.OPENAI, OpenAIAdapter)
        ProviderRegistry.register(Provider.ANTHROPIC, AnthropicAdapter)
        ProviderRegistry.register(Provider.MINIMAX, MiniMaxAdapter)

        # Initialize AI config
        self.ai_config = AIConfig()
        self.router = AIRouter(self.ai_config)
        self.memory = memory_store
        self.current_conversation: Optional[Conversation] = None
        self.work_folder: str = str(Path.cwd() / "workspace")

        # 工具执行器
        self.task_executor = TaskExecutor(self.work_folder)
        self.tool_parser = ToolCallParser(self.work_folder)

        # 上下文管理器 — 按 token 预算裁剪历史, 注入相关记忆
        # 关联一个 ContextCompressor 实现 per-conversation 自动压缩:
        # 当某对话用量超阈值时, 自动调 LLM 摘要早期消息并替换进 messages.
        from jarvis.core.context_compressor import (
            ContextCompressor,
            ThresholdTrigger,
        )
        self.context_compressor = ContextCompressor(
            router=self.router,
            trigger=ThresholdTrigger(threshold=0.75),
            keep_recent=4,
            cooldown_seconds=30.0,
            min_messages=6,
            persist_fn=self._save_conversation_to_file,
        )
        self.context_manager = ContextManager(compressor=self.context_compressor)

        # 子代理编排器 — 让主 LLM 通过 subagent 工具委派子任务
        # (注册到 task_executor, 主 LLM 可调用 researcher/coder/reviewer/...)
        # v3: 注入 memory_store 让每个 subagent 自动创建独立子会话
        from jarvis.core.subagent import SubagentOrchestrator
        self.subagent_orchestrator = SubagentOrchestrator(
            router=self.router,
            work_folder=self.work_folder,
            parent_conversation=None,    # 每次 chat/stream_chat 时动态更新
            message_store=self.memory,
            task_executor=self.task_executor,  # 让 subagent 可进入工具循环
        )
        self.task_executor.register_subagent(self.subagent_orchestrator)

    def _resolve_instance(self, provider_id: Optional[str] = None):
        """Resolve a ProviderInstance from provider_id or return active instance."""
        store = get_instance_store()
        if provider_id:
            inst = store.get_by_id(provider_id)
            if inst and inst.enabled:
                return inst
            logger.warning(f"[ChatEngine] provider_id={provider_id!r} not found or disabled, using active")
        return store.get_active_instance()

    def _build_system_prompt(self, settings: SystemPromptSettings = None) -> str:
        """构建系统提示词 — 从 workspace/prompts/*.md 文件拼接"""
        parts = []

        work_folder = settings.work_folder if settings and settings.work_folder else self.work_folder

        # 1. 读取 workspace/prompts/ 下的编号文件（按文件名排序）
        prompts_dir = Path(self.work_folder) / "prompts"
        if prompts_dir.exists():
            for f in sorted(prompts_dir.glob("*.md")):
                try:
                    content = f.read_text(encoding="utf-8").strip()
                    if content:
                        content = content.replace("{work_folder}", work_folder)
                        parts.append(content)
                except Exception as e:
                    logger.warning(f"Failed to read prompt file {f}: {e}")

        # 2. 技能列表 — workspace/skills/
        skills = load_skills()
        if skills:
            skill_lines = ["## 可用技能\n你可以使用以下技能辅助完成任务："]
            for s in skills:
                skill_lines.append(f"- **{s.name}**: {s.description}")
            parts.append("\n".join(skill_lines))

        # 3. 动态设置 — 从 Settings 注入（persona/abilities/memory）
        if settings and settings.persona:
            parts.append(f"## 角色设定\n{settings.persona}")
        if settings and settings.abilities:
            parts.append(f"## 能力说明\n{settings.abilities}")
        if settings and settings.memory:
            parts.append(f"## 记忆说明\n{settings.memory}")

        return "\n\n".join(parts)

    async def _load_prompt_settings(self) -> SystemPromptSettings:
        """从存储 + workspace 文件加载 Prompt 设置"""
        try:
            all_settings = await memory_store.get_all_settings()
            # Workspace 文件覆盖 DB 设置
            file_prompts = load_prompt_files()
            work_folder = all_settings.get("work_folder", "")
            return SystemPromptSettings(
                persona=file_prompts.get("persona") or all_settings.get("persona_prompt", ""),
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

                # 提取参数 — action 保留在 params 中 (FileOperationStrategy 需要)
                params = input_data.copy()
                action = params.get("action", "")

                tool_call = ToolCall(
                    tool=tool_name,
                    action=action,
                    params=params,
                    raw=block.get("id", json.dumps(block)),  # 优先使用 id
                    id=block.get("id", ""),
                )
                tool_calls.append(tool_call)
                logger.debug(f"[ChatEngine] 从 block 提取工具调用: {tool_name}.{action}")

        return tool_calls

    async def chat(
        self,
        user_input: str,
        conversation_id: Optional[str] = None,
        model: Optional[str] = None,
        stream: bool = False,
        provider_id: Optional[str] = None,
    ) -> dict:
        """处理对话 - 支持工具调用。返回 {text, topic}。"""
        logger.info(f"[Chat] 开始处理对话 | conv_id={conversation_id} | model={model} | input_len={len(user_input)}")
        logger.debug(f"[Chat] 用户输入: {user_input[:100]}...")

        # 1. 获取或创建对话上下文
        if conversation_id:
            conv_data = await self.memory.get_conversation(conversation_id)
            if conv_data:
                self.current_conversation = Conversation(
                    conversation_id=conversation_id,
                    user_id=conv_data.get("user_id", ""),
                    topic=conv_data.get("topic"),
                    messages=[Message(**m) for m in conv_data.get("messages", [])],
                    context=conv_data.get("context", {})
                )
                logger.info(f"[Chat] 从DB加载对话 | conv_id={conversation_id} | 消息数={len(conv_data.get('messages', []))} | topic={self.current_conversation.topic!r}")
            else:
                logger.info(f"[Chat] 对话不存在，创建新对话 | conv_id={conversation_id}")
                self.current_conversation = Conversation(conversation_id=conversation_id)
        else:
            logger.info("[Chat] 无conv_id，创建新对话")
            self.current_conversation = Conversation()

        # v3: 把当前会话注入 subagent 编排器, 让 LLM 调 subagent 时创建独立子会话
        self.subagent_orchestrator.parent_conversation = self.current_conversation
        # 让 subagent 跟随主对话的模型 / ProviderInstance
        instance = self._resolve_instance(provider_id)
        self.subagent_orchestrator.model = model
        self.subagent_orchestrator.instance = instance

        # 2. 添加用户消息
        self.current_conversation.add_message("user", user_input)
        logger.debug(f"[Chat] 用户消息已添加 | total_messages={len(self.current_conversation.messages)}")

        # 3. 加载 Prompt 设置
        prompt_settings = await self._load_prompt_settings()
        if prompt_settings.persona or prompt_settings.abilities or prompt_settings.memory or prompt_settings.tools:
            logger.info(f"[Chat] 已加载 Prompt 设置 | persona={'有' if prompt_settings.persona else '无'} | abilities={'有' if prompt_settings.abilities else '无'} | memory={'有' if prompt_settings.memory else '无'} | tools={'有' if prompt_settings.tools else '无'}")
        else:
            logger.debug("[Chat] 未配置自定义 Prompt 设置")

        # 4. 构建基础系统 Prompt
        system_prompt = self._build_system_prompt(prompt_settings)

        # 5. 通过 ContextManager 构建最终 messages:
        #    - 注入相关记忆 (默认 top_k=3)
        #    - 按 token 预算裁剪对话历史 (替代旧的硬编码 limit=10)
        history_dicts = [
            {"role": m.role, "content": m.content}
            for m in self.current_conversation.get_history(limit=10)
        ]
        # 关键: 移除刚加进去的 user_input, 因为 build_messages 会自动追加
        if history_dicts and history_dicts[-1].get("content") == user_input:
            history_dicts = history_dicts[:-1]

        ctx_result = await self.context_manager.build_messages(
            system_prompt=system_prompt,
            history=history_dicts,
            current_user_input=user_input,
            memory_retriever=self.memory.retrieve,
            model_id=model,
            memory_top_k=3,
            conversation=self.current_conversation,
        )
        messages = ctx_result["messages"]
        stats = ctx_result["stats"]
        logger.debug(
            f"[Chat] ContextManager | history_in={stats['history_in']} "
            f"history_out={stats['history_out']} dropped={stats['dropped']} "
            f"memory={stats['memory_chunks']} tokens~={stats['tokens_estimate']} "
            f"budget={stats['budget_available']}"
        )

        # 7. 工具调用迭代循环
        final_response = ""
        iteration_count = 0

        for iteration_count in range(MAX_TOOL_ITERATIONS):
            logger.debug(f"[Chat] 第 {iteration_count + 1} 次迭代，调用 LLM...")
            # 调用 LLM (传 instance, 与主对话 ProviderInstance 保持一致)
            response = await self.router.chat(
                messages,
                model=model,
                instance=instance,
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

            # 如果文本解析失败但有 content_blocks，尝试从 content_blocks 提取
            if not tool_calls and response.content_blocks:
                tool_calls = self._extract_tool_calls_from_blocks(response.content_blocks)
                logger.debug(f"[Chat] 从 content_blocks 提取到 {len(tool_calls)} 个工具调用")

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
                    err_detail = ""
                    if isinstance(result, dict) and status == "error":
                        err_detail = result.get("stderr") or result.get("message") or ""
                        logger.warning(f"[Chat] 工具错误详情: {str(err_detail)[:300]}")
                    logger.info(f"[Chat] 工具 {tool_call.tool}.{tool_call.action} 执行完成 | status={status}")
                    if isinstance(result, dict) and 'content' in result:
                        logger.debug(f"[Chat] 工具结果内容: {str(result['content'])[:100]}...")
                except Exception as e:
                    logger.error(f"[Chat] 工具执行错误: {tool_call.tool}.{tool_call.action} | error={e}")
                    result = {"status": "error", "message": str(e)}

                # 格式化结果 — Anthropic /v1/messages 要求严格的 tool_result 结构化块
                # 旧版走纯文本 user 消息会导致 Anthropic / MiniMax 代理抛 2013
                # 只在缺失 tool_use_id (本地正则解析得到) 的情况下才退回纯文本分支
                result_content = ToolResultFormatter.format_plain(
                    tool=tool_call.tool,
                    action=tool_call.action,
                    params=tool_call.params,
                    result=result,
                )
                self.current_conversation.add_message("tool_result", result_content)
                if tool_call.id:
                    # Anthropic/Ollama /v1/messages — 必须用 tool_result 块结构化引用 tool_use_id
                    messages.append({
                        "role": "user",
                        "content": [{
                            "type": "tool_result",
                            "tool_use_id": tool_call.id,
                            "content": result_content,
                        }],
                    })
                else:
                    # 本地 ToolCallParser.parse() 路径 — 没有 tool_use_id, 退回纯文本 user 消息
                    messages.append({"role": "user", "content": result_content})

            # 检查后续响应是否也有工具调用
            has_tools = self.tool_parser.has_tool_calls(response_text)
            if response.content_blocks:
                for block in response.content_blocks:
                    if block.get("type") == "tool_use":
                        has_tools = True
                        logger.debug(f"[Chat] 后续响应中发现 tool_use block")
                        break

        # 8. 添加助手消息（最终响应）
        thinking = response.thinking if isinstance(getattr(response, 'thinking', ''), str) else ""
        self.current_conversation.add_message("assistant", final_response, thinking=thinking)
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

        # 11. 第一轮对话: 自动生成主题 (不会覆盖已有主题)
        generated_topic = None
        if not self.current_conversation.topic:
            # First-turn condition: only user + assistant messages
            if all(m.role in ("user", "assistant", "tool", "tool_result")
                   for m in self.current_conversation.messages):
                # Skip if the first user message was image-only
                first_user = next(
                    (m for m in self.current_conversation.messages if m.role == "user"),
                    None,
                )
                if first_user and not first_user.image and first_user.content:
                    try:
                        generated_topic = await generate_topic(
                            self.router,
                            first_user.content,
                            model=model,
                            instance=instance,
                        )
                        self.current_conversation.set_topic(generated_topic)
                        await self.memory.update_conversation_topic(
                            self.current_conversation.conversation_id,
                            generated_topic,
                        )
                        logger.info(
                            f"[Chat] 已生成对话主题 | conv_id={self.current_conversation.conversation_id} | "
                            f"topic={generated_topic!r}"
                        )
                    except Exception as e:
                        logger.warning(f"[Chat] 主题生成失败: {e}")

        return {
            "text": self._resolve_image_paths(final_response),
            "topic": self.current_conversation.topic,
        }

    async def stream_chat(
        self,
        user_input: str,
        conversation_id: Optional[str] = None,
        model: Optional[str] = None,
        user_id: Optional[str] = None,
        provider_id: Optional[str] = None,
    ):
        """流式对话 - 两阶段：第一阶段执行工具，第二阶段流式返回。
        若为首轮对话,会在主流程结束后异步生成主题并 yield topic_update 事件。"""
        logger.info(f"[StreamChat] 开始处理 | conv_id={conversation_id} | user_id={user_id} | model={model} | input_len={len(user_input)}")

        # 1. 获取或创建对话上下文
        if conversation_id:
            conv_data = await self.memory.get_conversation(conversation_id)
            if conv_data:
                self.current_conversation = Conversation(
                    conversation_id=conversation_id,
                    user_id=conv_data.get("user_id", "") or user_id or "",
                    topic=conv_data.get("topic"),
                    messages=[Message(**m) for m in conv_data.get("messages", [])],
                    context=conv_data.get("context", {})
                )
                logger.info(f"[StreamChat] 从DB加载对话 | conv_id={conversation_id} | 消息数={len(conv_data.get('messages', []))} | topic={self.current_conversation.topic!r}")
            else:
                logger.info(f"[StreamChat] 对话不存在，创建新对话 | conv_id={conversation_id}")
                self.current_conversation = Conversation(conversation_id=conversation_id, user_id=user_id or "")
        else:
            logger.info("[StreamChat] 无conv_id，创建新对话")
            self.current_conversation = Conversation(user_id=user_id or "")

        # v3: 把当前会话注入 subagent 编排器
        self.subagent_orchestrator.parent_conversation = self.current_conversation
        # 解析 ProviderInstance — 主对话 / subagent / 后续工具迭代共用同一实例
        instance = self._resolve_instance(provider_id)
        self.subagent_orchestrator.model = model
        self.subagent_orchestrator.instance = instance

        # 2. 添加用户消息
        self.current_conversation.add_message("user", user_input)
        logger.debug(f"[StreamChat] 用户消息已添加 | total_messages={len(self.current_conversation.messages)}")

        # 3. 加载 Prompt 设置
        prompt_settings = await self._load_prompt_settings()
        logger.debug(f"[StreamChat] Prompt设置已加载 | persona={'有' if prompt_settings.persona else '无'}")

        # 4. 构建消息列表 — 通过 ContextManager 做 token 预算 + 记忆注入
        history_dicts = [
            {"role": m.role, "content": m.content}
            for m in self.current_conversation.get_history(limit=10)
        ]
        # build_messages 会自动追加 user_input, 这里去掉末尾重复
        if history_dicts and history_dicts[-1].get("content") == user_input:
            history_dicts = history_dicts[:-1]

        ctx_result = await self.context_manager.build_messages(
            system_prompt=self._build_system_prompt(prompt_settings),
            history=history_dicts,
            current_user_input=user_input,
            memory_retriever=self.memory.retrieve,
            model_id=model,
            memory_top_k=3,
            conversation=self.current_conversation,
        )
        messages = ctx_result["messages"]
        logger.debug(
            f"[StreamChat] ContextManager | "
            f"history_in={ctx_result['stats']['history_in']} "
            f"history_out={ctx_result['stats']['history_out']} "
            f"dropped={ctx_result['stats']['dropped']} "
            f"memory={ctx_result['stats']['memory_chunks']} "
            f"tokens~={ctx_result['stats']['tokens_estimate']}"
        )

        # 5. 第一阶段：流式调用，实时输出文本/思考，同时检测工具调用
        import time as _t
        _t0 = _t.time()
        logger.debug("[StreamChat] 调用 LLM (第一阶段流式)...")
        streamed_text = ""
        streamed_thinking = ""
        tool_uses: list[dict] = []
        content_blocks: list[dict] = []
        current_tool: dict | None = None

        async for event in self.router.chat_stream_full(messages, model=model, instance=instance):
            etype = event.get("type", "")

            if etype == "thinking_start":
                yield json.dumps({"type": "thinking_start", "content": ""})

            elif etype == "thinking":
                chunk = event["content"]
                streamed_thinking += chunk
                yield json.dumps({"type": "thinking", "content": chunk})

            elif etype == "thinking_end":
                yield json.dumps({"type": "thinking_end", "content": ""})
                if streamed_thinking:
                    content_blocks.append({"type": "thinking", "thinking": streamed_thinking})

            elif etype == "text":
                chunk = event["content"]
                streamed_text += chunk
                yield chunk  # ← 直接流式输出到前端

            elif etype == "tool_use_start":
                current_tool = {
                    "type": "tool_use",
                    "name": event["name"],
                    "id": event["id"],
                    "input": {},
                }
                yield json.dumps({"type": "status", "content": "tool_detected"})

            elif etype == "tool_use_end":
                if current_tool:
                    current_tool["input"] = event.get("input", {})
                    tool_uses.append(current_tool)
                    content_blocks.append(current_tool)
                    current_tool = None

            elif etype == "message_stop":
                break

            elif etype == "error":
                logger.error(f"[StreamChat] stream error: {event['content']}")
                break

        if streamed_text:
            content_blocks.append({"type": "text", "text": streamed_text})

        logger.info(
            f"[StreamChat] 第一阶段流式完成 | text_len={len(streamed_text)} | "
            f"thinking_len={len(streamed_thinking)} | tool_uses={len(tool_uses)} | "
            f"耗时={(_t.time()-_t0)*1000:.0f}ms"
        )

        # 6. 检测并执行工具调用（如有）
        final_response = streamed_text
        thinking = streamed_thinking
        has_tools = len(tool_uses) > 0

        for iteration_count in range(MAX_TOOL_ITERATIONS):
            if not has_tools:
                logger.debug("[StreamChat] 无工具调用，结束迭代")
                break

            yield json.dumps({"type": "status", "content": f"tool_iter_{iteration_count + 1}"})

            tool_calls: list[ToolCall] = []
            for tu in tool_uses:
                tool_name = tu.get("name", "")
                if not tool_name or tool_name not in tool_registry.get_tool_names():
                    logger.warning(f"[StreamChat] 未知工具: {tool_name}")
                    continue
                params = tu.get("input", {})
                action = params.get("action", "")
                tc = ToolCall(
                    tool=tool_name,
                    action=action,
                    params=params,
                    raw=tu.get("id", json.dumps(tu)),
                    id=tu.get("id", ""),
                )
                tool_calls.append(tc)

            if not tool_calls:
                break

            logger.info(f"[StreamChat] 第 {iteration_count + 1} 次迭代: 发现 {len(tool_calls)} 个工具调用")
            for tc in tool_calls:
                logger.info(f"[StreamChat] 工具调用: {tc.tool}.{tc.action} | params={tc.params}")
                yield json.dumps({
                    "type": "tool_call",
                    "tool": tc.tool,
                    "action": tc.action,
                    "params": tc.params,
                })

            messages.append({"role": "assistant", "content": content_blocks})

            for tool_call in tool_calls:
                step = Step(tool=tool_call.tool, params=tool_call.params)

                tool_call_message = {
                    "tool": tool_call.tool,
                    "action": tool_call.action,
                    "params": tool_call.params,
                    "raw": tool_call.raw,
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

                result_content = ToolResultFormatter.format_plain(
                    tool=tool_call.tool,
                    action=tool_call.action,
                    params=tool_call.params,
                    result=result,
                )
                self.current_conversation.add_message("tool_result", result_content)
                if tool_call.id:
                    # Anthropic/Ollama /v1/messages — 必须用 tool_result 块结构化引用 tool_use_id
                    messages.append({
                        "role": "user",
                        "content": [{
                            "type": "tool_result",
                            "tool_use_id": tool_call.id,
                            "content": result_content,
                        }],
                    })
                else:
                    # 本地 ToolCallParser.parse() 路径 — 没有 tool_use_id, 退回纯文本 user 消息
                    messages.append({"role": "user", "content": result_content})

                yield json.dumps({
                    "type": "tool_result",
                    "tool": tool_call.tool,
                    "action": tool_call.action,
                    "status": result.get("status", "success"),
                    "result": result,
                })

            _t1 = _t.time()
            logger.debug(f"[StreamChat] 再次调用 LLM (迭代 {iteration_count + 1})...")
            response = await self.router.chat(messages, model=model, instance=instance, stream=False)
            response_text = response.content
            thinking = response.thinking if isinstance(getattr(response, 'thinking', ''), str) else ""
            final_response = response_text
            content_blocks = (
                response.content_blocks
                if response.content_blocks
                else [{"type": "text", "text": response_text}]
            )
            logger.info(
                f"[StreamChat] LLM 后续响应 | len={len(response_text)} | "
                f"耗时={(_t.time()-_t1)*1000:.0f}ms"
            )

            tool_uses = []
            has_tools = self.tool_parser.has_tool_calls(response_text)
            if response.content_blocks:
                for block in response.content_blocks:
                    if block.get("type") == "tool_use":
                        has_tools = True
                        tool_uses.append(block)
                        logger.debug(f"[StreamChat] 后续响应中发现 tool_use block")
                        break

        # 7. 解析响应中的本地图片路径 → base64
        final_response = self._resolve_image_paths(final_response)

        # 8. 保存对话历史
        self.current_conversation.add_message("assistant", final_response, thinking=thinking)
        save_result = await self.memory.save_conversation(
            self.current_conversation.conversation_id,
            self.current_conversation.user_id,
            [msg.to_dict() for msg in self.current_conversation.messages],
            self.current_conversation.context
        )
        logger.info(f"[StreamChat] 对话已保存 | conv_id={self.current_conversation.conversation_id} | success={save_result}")

        # 9. 保存对话到 JSON 文件
        await self._save_conversation_to_file()

        # 10. 流式返回后续 thinking（仅当工具执行后的新 thinking 与第一阶段不同时）
        if thinking and thinking != streamed_thinking:
            logger.info(f"[StreamChat] 流式返回后续 thinking | len={len(thinking)}")
            yield json.dumps({"type": "thinking_start", "content": ""})
            for chunk in self._chunk_text(thinking, 8):
                yield json.dumps({"type": "thinking", "content": chunk})
            yield json.dumps({"type": "thinking_end", "content": ""})

        # 11. 流式返回后续响应（仅当工具执行产生了新文本时）
        if final_response != streamed_text:
            logger.info(f"[StreamChat] 流式返回后续响应 | len={len(final_response)}")
            for chunk in self._chunk_text(final_response, 8):
                yield chunk

        # 12. 首轮对话: 异步生成主题 (主流程已结束,不影响响应延迟)
        if not self.current_conversation.topic:
            first_user = next(
                (m for m in self.current_conversation.messages if m.role == "user"),
                None,
            )
            if first_user and not first_user.image and first_user.content:
                async for evt in self._generate_and_yield_topic(
                    first_user.content, model=model, instance=instance
                ):
                    yield evt

        logger.info("[StreamChat] 流式返回完成")

    async def stream_chat_with_messages(
        self,
        user_input: str,
        messages_history: list[dict],
        model: Optional[str] = None,
        conversation_id: Optional[str] = None,
        user_id: Optional[str] = None,
        provider_id: Optional[str] = None,
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
                    topic=conv_data.get("topic"),
                    messages=[Message(**m) for m in conv_data.get("messages", [])],
                    context=conv_data.get("context", {})
                )
                logger.info(f"[StreamChatWithMsgs] 从DB加载对话 | conv_id={conversation_id} | 消息数={len(conv_data.get('messages', []))} | topic={self.current_conversation.topic!r}")
            else:
                logger.info(f"[StreamChatWithMsgs] 对话不存在，创建新对话 | conv_id={conversation_id}")
                self.current_conversation = Conversation(conversation_id=conversation_id, user_id=user_id or "")
        else:
            logger.info("[StreamChatWithMsgs] 无conv_id，创建新对话")
            self.current_conversation = Conversation(user_id=user_id or "")
            logger.debug("[StreamChatWithMsgs] 新建空对话上下文")

        # v3: 把当前会话注入 subagent 编排器
        self.subagent_orchestrator.parent_conversation = self.current_conversation
        # 解析 ProviderInstance — 主对话 / subagent / 后续工具迭代共用同一实例
        instance = self._resolve_instance(provider_id)
        self.subagent_orchestrator.model = model
        self.subagent_orchestrator.instance = instance

        # 2. 添加用户消息
        self.current_conversation.add_message("user", user_input)
        logger.debug(f"[StreamChatWithMsgs] 用户消息已添加 | total_messages={len(self.current_conversation.messages)}")

        # 3. 加载 Prompt 设置
        prompt_settings = await self._load_prompt_settings()
        logger.debug(f"[StreamChatWithMsgs] Prompt设置已加载")

        # 4. 构建消息列表 - 使用传入的历史 (走 ContextManager 做预算裁剪)
        history_filtered = [m for m in messages_history if m.get("role") != "system"]

        ctx_result = await self.context_manager.build_messages(
            system_prompt=self._build_system_prompt(prompt_settings),
            history=history_filtered,
            current_user_input=user_input,
            memory_retriever=self.memory.retrieve,
            model_id=model,
            memory_top_k=3,
            conversation=self.current_conversation,
        )
        messages = ctx_result["messages"]
        history_count = ctx_result["stats"]["history_out"]
        logger.debug(
            f"[StreamChatWithMsgs] ContextManager | "
            f"history_in={ctx_result['stats']['history_in']} "
            f"history_out={history_count} "
            f"dropped={ctx_result['stats']['dropped']} "
            f"memory={ctx_result['stats']['memory_chunks']}"
        )

        # 5. 第一阶段：流式调用，实时输出文本/思考，同时检测工具调用
        import time as _t
        _t0 = _t.time()
        logger.debug("[StreamChatWithMsgs] 调用 LLM (第一阶段流式)...")
        streamed_text = ""
        streamed_thinking = ""
        tool_uses: list[dict] = []
        content_blocks: list[dict] = []
        current_tool: dict | None = None

        async for event in self.router.chat_stream_full(messages, model=model, instance=instance):
            etype = event.get("type", "")

            if etype == "thinking_start":
                yield json.dumps({"type": "thinking_start", "content": ""})

            elif etype == "thinking":
                chunk = event["content"]
                streamed_thinking += chunk
                yield json.dumps({"type": "thinking", "content": chunk})

            elif etype == "thinking_end":
                yield json.dumps({"type": "thinking_end", "content": ""})
                if streamed_thinking:
                    content_blocks.append({"type": "thinking", "thinking": streamed_thinking})

            elif etype == "text":
                chunk = event["content"]
                streamed_text += chunk
                yield chunk  # ← 直接流式输出到前端，消除 TTFB 延迟

            elif etype == "tool_use_start":
                current_tool = {
                    "type": "tool_use",
                    "name": event["name"],
                    "id": event["id"],
                    "input": {},
                }
                # 通知前端检测到工具调用
                yield json.dumps({"type": "status", "content": "tool_detected"})

            elif etype == "tool_use_end":
                if current_tool:
                    current_tool["input"] = event.get("input", {})
                    tool_uses.append(current_tool)
                    content_blocks.append(current_tool)
                    current_tool = None

            elif etype == "message_stop":
                break

            elif etype == "error":
                logger.error(f"[StreamChatWithMsgs] stream error: {event['content']}")
                break

        # Add text block to content_blocks for message history
        if streamed_text:
            content_blocks.append({"type": "text", "text": streamed_text})

        logger.info(
            f"[StreamChatWithMsgs] 第一阶段流式完成 | text_len={len(streamed_text)} | "
            f"thinking_len={len(streamed_thinking)} | tool_uses={len(tool_uses)} | "
            f"耗时={(_t.time()-_t0)*1000:.0f}ms"
        )

        # 6. 检测并执行工具调用（如有）
        final_response = streamed_text
        thinking = streamed_thinking
        has_tools = len(tool_uses) > 0

        for iteration_count in range(MAX_TOOL_ITERATIONS):
            if not has_tools:
                logger.debug("[StreamChatWithMsgs] 无工具调用，结束迭代")
                break

            yield json.dumps({"type": "status", "content": f"tool_iter_{iteration_count + 1}"})

            # Convert tool_uses dicts to ToolCall objects
            tool_calls: list[ToolCall] = []
            for tu in tool_uses:
                tool_name = tu.get("name", "")
                if not tool_name or tool_name not in tool_registry.get_tool_names():
                    logger.warning(f"[StreamChatWithMsgs] 未知工具: {tool_name}")
                    continue
                params = tu.get("input", {})
                action = params.get("action", "")
                tc = ToolCall(
                    tool=tool_name,
                    action=action,
                    params=params,
                    raw=tu.get("id", json.dumps(tu)),
                    id=tu.get("id", ""),
                )
                tool_calls.append(tc)

            if not tool_calls:
                break

            logger.info(f"[StreamChatWithMsgs] 第 {iteration_count + 1} 次迭代: 发现 {len(tool_calls)} 个工具调用")
            for tc in tool_calls:
                logger.info(f"[StreamChatWithMsgs] 工具调用: {tc.tool}.{tc.action} | params={tc.params}")
                yield json.dumps({
                    "type": "tool_call",
                    "tool": tc.tool,
                    "action": tc.action,
                    "params": tc.params,
                })

            # Add assistant response (with tool_use blocks) to message history
            messages.append({"role": "assistant", "content": content_blocks})

            # Execute tools
            for tool_call in tool_calls:
                step = Step(tool=tool_call.tool, params=tool_call.params)

                tool_call_message = {
                    "tool": tool_call.tool,
                    "action": tool_call.action,
                    "params": tool_call.params,
                    "raw": tool_call.raw,
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

                result_content = ToolResultFormatter.format_plain(
                    tool=tool_call.tool,
                    action=tool_call.action,
                    params=tool_call.params,
                    result=result,
                )
                self.current_conversation.add_message("tool_result", result_content)
                if tool_call.id:
                    # Anthropic/Ollama /v1/messages — 必须用 tool_result 块结构化引用 tool_use_id
                    messages.append({
                        "role": "user",
                        "content": [{
                            "type": "tool_result",
                            "tool_use_id": tool_call.id,
                            "content": result_content,
                        }],
                    })
                else:
                    # 本地 ToolCallParser.parse() 路径 — 没有 tool_use_id, 退回纯文本 user 消息
                    messages.append({"role": "user", "content": result_content})

                yield json.dumps({
                    "type": "tool_result",
                    "tool": tool_call.tool,
                    "action": tool_call.action,
                    "status": result.get("status", "success"),
                    "result": result,
                })

            # 再次调用 LLM 获取响应（后续迭代仍用非流式，因为前面已有工具进度反馈）
            _t1 = _t.time()
            logger.debug(f"[StreamChatWithMsgs] 再次调用 LLM (迭代 {iteration_count + 1})...")
            response = await self.router.chat(messages, model=model, instance=instance, stream=False)
            response_text = response.content
            thinking = response.thinking if isinstance(getattr(response, 'thinking', ''), str) else ""
            final_response = response_text
            content_blocks = (
                response.content_blocks
                if response.content_blocks
                else [{"type": "text", "text": response_text}]
            )
            logger.info(
                f"[StreamChatWithMsgs] LLM 后续响应 | len={len(response_text)} | "
                f"耗时={(_t.time()-_t1)*1000:.0f}ms"
            )

            # 检查后续响应是否也有工具调用
            tool_uses = []
            has_tools = self.tool_parser.has_tool_calls(response_text)
            if response.content_blocks:
                for block in response.content_blocks:
                    if block.get("type") == "tool_use":
                        has_tools = True
                        tool_uses.append(block)
                        logger.debug(
                            f"[StreamChatWithMsgs] 后续响应中发现 tool_use block: "
                            f"{block.get('name', 'unknown')}"
                        )
                        break

        # 7. 解析响应中的本地图片路径 → base64
        final_response = self._resolve_image_paths(final_response)

        # 8. 保存对话历史
        self.current_conversation.add_message("assistant", final_response, thinking=thinking)
        save_result = await self.memory.save_conversation(
            self.current_conversation.conversation_id,
            self.current_conversation.user_id,
            [msg.to_dict() for msg in self.current_conversation.messages],
            self.current_conversation.context
        )
        logger.info(f"[StreamChatWithMsgs] 对话已保存 | conv_id={self.current_conversation.conversation_id} | success={save_result}")

        # 9. 保存对话到 JSON 文件
        await self._save_conversation_to_file()

        # 10. 流式返回后续 thinking（仅当工具执行后的新 thinking 与第一阶段不同时）
        if thinking and thinking != streamed_thinking:
            logger.info(f"[StreamChatWithMsgs] 流式返回后续 thinking | len={len(thinking)}")
            yield json.dumps({"type": "thinking_start", "content": ""})
            for chunk in self._chunk_text(thinking, 8):
                yield json.dumps({"type": "thinking", "content": chunk})
            yield json.dumps({"type": "thinking_end", "content": ""})

        # 11. 流式返回后续响应（仅当工具执行产生了新文本时）
        if final_response != streamed_text:
            logger.info(f"[StreamChatWithMsgs] 流式返回后续响应 | len={len(final_response)}")
            for chunk in self._chunk_text(final_response, 8):
                yield chunk

        # 12. 首轮对话: 异步生成主题
        if not self.current_conversation.topic:
            first_user = next(
                (m for m in self.current_conversation.messages if m.role == "user"),
                None,
            )
            if first_user and not first_user.image and first_user.content:
                async for evt in self._generate_and_yield_topic(
                    first_user.content, model=model, instance=instance
                ):
                    yield evt

        logger.info("[StreamChatWithMsgs] 流式返回完成")

    async def _generate_and_yield_topic(self, user_input: str,
                                        model: Optional[str] = None,
                                        instance=None):
        """生成主题 → 持久化 → yield topic_update 事件。
        主流程已结束时调用,不影响响应延迟。"""
        try:
            topic = await generate_topic(self.router, user_input,
                                         model=model, instance=instance)
            # 防止覆盖用户已编辑的主题
            if self.current_conversation.topic:
                logger.info(
                    f"[Chat] 主题已被用户设置,跳过自动生成: "
                    f"current={self.current_conversation.topic!r} generated={topic!r}"
                )
                return
            self.current_conversation.set_topic(topic)
            await self.memory.update_conversation_topic(
                self.current_conversation.conversation_id, topic
            )
            logger.info(
                f"[Chat] 已生成对话主题 | conv_id={self.current_conversation.conversation_id} | "
                f"topic={topic!r}"
            )
            yield json.dumps({"type": "topic_update", "topic": topic})
        except Exception as e:
            logger.warning(f"[Chat] 主题生成失败: {e}")

    @staticmethod
    def _chunk_text(text: str, size: int = 8):
        """Yield text in chunks for streaming"""
        for i in range(0, len(text), size):
            yield text[i:i + size]

    def _resolve_image_paths(self, text: str) -> str:
        """将响应中的本地图片路径替换为 base64 data URL.

        匹配: ![alt](workspace/xxx.png) 或 ![alt](./xxx.png)
        """
        img_re = re.compile(r'!\[([^\]]*)\]\(([^)]+)\)')

        def replacer(match: re.Match) -> str:
            alt = match.group(1)
            filepath = match.group(2)
            # Try to resolve relative to work_folder
            path = Path(filepath)
            if not path.is_absolute():
                path = Path(self.work_folder) / path
            if not path.exists():
                return match.group(0)  # leave as-is
            try:
                data = path.read_bytes()
                ext = path.suffix.lower()
                mime = {".png": "image/png", ".jpg": "image/jpeg",
                        ".jpeg": "image/jpeg", ".gif": "image/gif",
                        ".webp": "image/webp", ".bmp": "image/bmp"}.get(ext, "image/png")
                b64 = base64.b64encode(data).decode()
                return f"![{alt}](data:{mime};base64,{b64})"
            except Exception as e:
                logger.warning(f"Failed to resolve image {path}: {e}")
                return match.group(0)

        return img_re.sub(replacer, text)

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
        # Sync-check Ollama health (cached; no async here)
        return {
            "current_conversation": {
                "conversation_id": self.current_conversation.conversation_id if self.current_conversation else None,
                "messages_count": len(self.current_conversation.messages) if self.current_conversation else 0
            },
            "ollama_connected": self._cached_ollama_ok,
        }

    @property
    def _cached_ollama_ok(self) -> bool:
        """Cached Ollama health — updated by health check polling."""
        return getattr(self, '_ollama_ok', True)  # default True until proven otherwise