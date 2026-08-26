# jarvis/core/chat_engine.py
"""对话引擎 - 核心业务逻辑"""
from __future__ import annotations

import json
import base64
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Any
from jarvis.core.entities import Message, Conversation
from jarvis.core.memory_store import memory_store
from jarvis.core.task_engine import TaskExecutor
from jarvis.core.tool_parser import ToolCallParser, ToolCall
from jarvis.core.tool_result_formatter import ToolResultFormatter
from jarvis.core.tool_registry import tool_registry
from jarvis.core.agent_loop import AgentLoopRunner, AgentLoopResult, AgentLoopConfig
from jarvis.services.ai import AIRouter, AIConfig, ProviderRegistry
from jarvis.services.ai.providers import OllamaAdapter, OpenAIAdapter, AnthropicAdapter, MiniMaxAdapter
from jarvis.services.ai.models import Provider
from jarvis.services.ai.instance_config import get_instance_store
from jarvis.services.skill_loader import load_prompt_files
from jarvis.services.skill_store import get_skill_store
from jarvis.core.topic_generator import generate_topic
from jarvis.core.context_manager import ContextManager
from jarvis.utils.logger import get_logger

logger = get_logger(__name__)


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

        # Agent Loop Runner — 三处入口 (chat/stream_chat/stream_chat_with_messages) 共用.
        # PR2 引入: 修 chat() 漏 assistant turn 的核心 bug + 加 hint/dedup/parallel.
        # max_iterations / provider_protocol 由每次对话根据 Settings 和 instance 动态注入.
        self.agent_loop_runner = AgentLoopRunner(
            config=AgentLoopConfig(
                max_iterations=8,                # PR2 默认 8; PR4 改为从 Settings 读
                provider_protocol="anthropic",   # PR3 改为按 instance.type 动态判断
                parallel_tool_exec=True,
                dedup_tool_calls=True,
                inject_iteration_hint=True,
                inject_stop_hint_on_max=True,
            ),
            task_executor=self.task_executor,
            tool_parser=self.tool_parser,
        )

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

    def _resolve_provider_protocol(self, instance) -> str:
        """PR3: 根据 instance.type 决定 tool-call 协议.

        - "openai" / "minimax" → "openai" (tool_calls + role=tool)
        - "ollama" / "anthropic" → "anthropic" (tool_use blocks + user tool_result)
        - 默认回退到 "anthropic"
        """
        if instance is None:
            return "anthropic"
        prov_type = (getattr(instance, "type", "") or "").lower()
        if prov_type in ("openai", "minimax"):
            return "openai"
        return "anthropic"

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

        # 2. 技能列表 — 来自 SkillStore (内存缓存, 按 enabled + active_groups 过滤)
        skills = get_skill_store().get_enabled_for_active_groups()
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

    async def _apply_runtime_settings(self) -> None:
        """PR4: 从 Settings 读 tool_loop_max_iterations, 注入 runner + subagent.

        调用时机: chat / stream_chat / stream_chat_with_messages 开头, 用户改了 Settings
        后下次对话立刻生效.
        """
        try:
            all_settings = await memory_store.get_all_settings()
            v = all_settings.get("tool_loop_max_iterations")
            if v is None:
                return  # 用 runner 默认值 8
            n = int(v)
            # 安全夹紧 (Settings UI 限制 1-20, 后端再保一道)
            n = max(1, min(20, n))
            self.agent_loop_runner.config.max_iterations = n
            self.subagent_orchestrator.max_iterations = n
            logger.debug(
                f"[ChatEngine] max_iterations 从 Settings 注入: {n}"
            )
        except Exception as e:
            logger.warning(f"[ChatEngine] 读 tool_loop_max_iterations 失败: {e}")

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
                    id=block.get("id", ""),              # __post_init__ 兜底生成稳定哈希
                    raw_input_json=json.dumps(block),    # 原始 block JSON, 仅 debug
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

        # PR4: 从 Settings 注入 max_iterations (主对话 + subagent 同步)
        await self._apply_runtime_settings()

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

        # 7. Phase 1: 调 LLM (非流式, 一次)
        logger.debug("[Chat] Phase 1: 调 LLM...")
        response = await self.router.chat(
            messages, model=model, instance=instance, stream=False
        )
        response_text = response.content or ""
        response_thinking = (
            response.thinking
            if isinstance(getattr(response, "thinking", ""), str)
            else ""
        )
        content_blocks = response.content_blocks or []
        tool_uses = AgentLoopRunner._extract_tool_uses(content_blocks, response_text)

        # 7a. 无工具调用 → 直接返回 (修核心 bug 前的旧行为)
        if not tool_uses:
            logger.info(
                f"[Chat] Phase 1 无工具调用 | text_len={len(response_text)} | 直接返回"
            )
            self.current_conversation.add_message(
                "assistant", response_text, thinking=response_thinking
            )
            # 保存 + 主题生成 与正常路径一致
            save_result = await self.memory.save_conversation(
                self.current_conversation.conversation_id,
                self.current_conversation.user_id,
                [msg.to_dict() for msg in self.current_conversation.messages],
                self.current_conversation.context
            )
            logger.info(
                f"[Chat] 对话已保存 | conv_id={self.current_conversation.conversation_id} "
                f"| success={save_result}"
            )
            await self._save_conversation_to_file()
            # 保存相关记忆（如果是有意义的信息）
            if len(user_input) > 10 and "记住" in user_input:
                key = user_input[:50].strip()
                save_mem_result = await self.memory.save(key, user_input)
                logger.info(f"[Chat] 保存记忆 | key={key} | success={save_mem_result}")
            generated_topic = await self._generate_topic_for_first_turn(
                user_input, model=model, instance=instance
            )
            return {
                "text": self._resolve_image_paths(response_text),
                "topic": generated_topic or self.current_conversation.topic,
            }

        # 7b. Phase 2+: 调公共 AgentLoopRunner — 修复 chat() 漏 assistant turn 的核心 bug
        # PR3: 按 instance.type 动态切 provider_protocol (OpenAI / MiniMax 用 openai 协议)
        self.agent_loop_runner.config.provider_protocol = (
            self._resolve_provider_protocol(instance)
        )
        final_result: Optional[AgentLoopResult] = None
        async for event in self.agent_loop_runner.run_iterations(
            messages, self.router,
            model=model, instance=instance,
            current_text=response_text,
            current_thinking=response_thinking,
            current_content_blocks=content_blocks,
            current_tool_uses=tool_uses,
        ):
            etype = event.get("type", "")

            if etype == "tool_iter":
                logger.info(
                    f"[Chat] AgentLoop iter {event['iteration']}/{event['max']}"
                )

            elif etype == "tool_call":
                # 持久化: 记录 tool 调用 (与旧实现一致)
                tool_call_message = {
                    "tool": event["tool"],
                    "action": event["action"],
                    "params": event["params"],
                }
                self.current_conversation.add_message(
                    "tool", json.dumps(tool_call_message)
                )
                logger.info(
                    f"[Chat] 工具调用: {event['tool']}.{event['action']} | "
                    f"params={event['params']}"
                )

            elif etype == "tool_result":
                # 持久化: 记录 tool_result (与旧实现一致)
                result_content = ToolResultFormatter.format_plain(
                    tool=event["tool"],
                    action=event["action"],
                    params=event.get("params", {}),
                    result=event["result"],
                )
                self.current_conversation.add_message("tool_result", result_content)
                status = (
                    event["result"].get("status", "success")
                    if isinstance(event["result"], dict)
                    else "success"
                )
                logger.info(
                    f"[Chat] 工具 {event['tool']}.{event['action']} 执行完成 | "
                    f"status={status}"
                )

            elif etype == "tool_skipped":
                # dedup: 重复调用, 记录但不执行
                tool_call_message = {
                    "tool": event["tool"],
                    "skipped": True,
                    "reason": event.get("reason", ""),
                }
                self.current_conversation.add_message(
                    "tool", json.dumps(tool_call_message)
                )
                logger.info(
                    f"[Chat] 工具重复跳过: {event['tool']} | "
                    f"reason={event.get('reason', '')}"
                )

            elif etype == "result":
                final_result = event["result"]

        if final_result is None:
            # 防御性: runner 没产出 result 事件时, 用 Phase 1 响应兜底
            logger.warning("[Chat] AgentLoopRunner 未返回 result, 兜底使用 Phase 1 响应")
            final_result = AgentLoopResult(
                final_text=response_text,
                final_thinking=response_thinking,
                iterations_used=1,
            )

        # 8. 添加助手消息 (最终响应) + 持久化
        self.current_conversation.add_message(
            "assistant", final_result.final_text,
            thinking=final_result.final_thinking,
        )
        logger.info(
            f"[Chat] 对话完成 | iterations={final_result.iterations_used} | "
            f"max_reached={final_result.max_iterations_reached} | "
            f"total_messages={len(self.current_conversation.messages)}"
        )

        if final_result.max_iterations_reached:
            logger.warning(
                f"[Chat] 达到最大工具迭代次数 ({self.agent_loop_runner.config.max_iterations})"
            )

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

        # 12. 第一轮对话: 自动生成主题 (不会覆盖已有主题)
        generated_topic = await self._generate_topic_for_first_turn(
            user_input, model=model, instance=instance
        )

        return {
            "text": self._resolve_image_paths(final_result.final_text),
            "topic": generated_topic or self.current_conversation.topic,
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

        # PR4: 从 Settings 注入 max_iterations (主对话 + subagent 同步)
        await self._apply_runtime_settings()

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

        # 6. Phase 2+: 通过 AgentLoopRunner 跑工具循环 (修 chat() 漏 assistant turn 的核心 bug)
        final_response = streamed_text
        thinking = streamed_thinking
        phase1_text = streamed_text

        if tool_uses:
            # PR3: 按 instance.type 动态切 provider_protocol
            self.agent_loop_runner.config.provider_protocol = (
                self._resolve_provider_protocol(instance)
            )
            # Phase 1 的 assistant turn 已经在 content_blocks 中, runner 会复用
            # runner 会自动注入 assistant turn (含 tool_use) + tool_result, 修核心 bug
            final_result: Optional[AgentLoopResult] = None
            async for event in self.agent_loop_runner.run_iterations(
                messages, self.router,
                model=model, instance=instance,
                current_text=streamed_text,
                current_thinking=streamed_thinking,
                current_content_blocks=content_blocks,
                current_tool_uses=tool_uses,
            ):
                etype = event.get("type", "")

                if etype == "tool_iter":
                    yield json.dumps({
                        "type": "status",
                        "content": f"tool_iter_{event['iteration']}",
                    })

                elif etype == "tool_call":
                    # SSE 通知前端 + 持久化
                    yield json.dumps({
                        "type": "tool_call",
                        "tool": event["tool"],
                        "action": event["action"],
                        "params": event["params"],
                    })
                    self.current_conversation.add_message(
                        "tool",
                        json.dumps({
                            "tool": event["tool"],
                            "action": event["action"],
                            "params": event["params"],
                        }),
                    )
                    logger.info(
                        f"[StreamChat] 工具调用: {event['tool']}.{event['action']} "
                        f"| params={event['params']}"
                    )

                elif etype == "tool_skipped":
                    self.current_conversation.add_message(
                        "tool",
                        json.dumps({
                            "tool": event["tool"],
                            "skipped": True,
                            "reason": event.get("reason", ""),
                        }),
                    )

                elif etype == "tool_result":
                    result = event["result"]
                    status = (
                        result.get("status", "success")
                        if isinstance(result, dict)
                        else "success"
                    )
                    result_content = ToolResultFormatter.format_plain(
                        tool=event["tool"],
                        action=event["action"],
                        params=event.get("params", {}),
                        result=result,
                    )
                    self.current_conversation.add_message("tool_result", result_content)
                    logger.info(
                        f"[StreamChat] 工具 {event['tool']}.{event['action']} "
                        f"执行完成 | status={status}"
                    )
                    yield json.dumps({
                        "type": "tool_result",
                        "tool": event["tool"],
                        "action": event["action"],
                        "status": status,
                        "result": result,
                    })

                elif etype == "result":
                    final_result = event["result"]

            if final_result is None:
                logger.warning(
                    "[StreamChat] AgentLoopRunner 未返回 result, 兜底使用 Phase 1 响应"
                )
                final_result = AgentLoopResult(
                    final_text=streamed_text,
                    final_thinking=streamed_thinking,
                    iterations_used=1,
                )

            final_response = final_result.final_text
            thinking = final_result.final_thinking
            if final_result.max_iterations_reached:
                logger.warning(
                    f"[StreamChat] 达到最大工具迭代次数 "
                    f"({self.agent_loop_runner.config.max_iterations})"
                )

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
        if final_response != phase1_text:
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

        # PR4: 从 Settings 注入 max_iterations (主对话 + subagent 同步)
        await self._apply_runtime_settings()

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

        # 6. Phase 2+: 通过 AgentLoopRunner 跑工具循环 (修 chat() 漏 assistant turn 的核心 bug)
        final_response = streamed_text
        thinking = streamed_thinking
        phase1_text = streamed_text

        if tool_uses:
            # PR3: 按 instance.type 动态切 provider_protocol
            self.agent_loop_runner.config.provider_protocol = (
                self._resolve_provider_protocol(instance)
            )
            # runner 会自动注入 assistant turn (含 tool_use) + tool_result, 修核心 bug
            final_result: Optional[AgentLoopResult] = None
            async for event in self.agent_loop_runner.run_iterations(
                messages, self.router,
                model=model, instance=instance,
                current_text=streamed_text,
                current_thinking=streamed_thinking,
                current_content_blocks=content_blocks,
                current_tool_uses=tool_uses,
            ):
                etype = event.get("type", "")

                if etype == "tool_iter":
                    yield json.dumps({
                        "type": "status",
                        "content": f"tool_iter_{event['iteration']}",
                    })

                elif etype == "tool_call":
                    yield json.dumps({
                        "type": "tool_call",
                        "tool": event["tool"],
                        "action": event["action"],
                        "params": event["params"],
                    })
                    self.current_conversation.add_message(
                        "tool",
                        json.dumps({
                            "tool": event["tool"],
                            "action": event["action"],
                            "params": event["params"],
                        }),
                    )
                    logger.info(
                        f"[StreamChatWithMsgs] 工具调用: {event['tool']}.{event['action']} "
                        f"| params={event['params']}"
                    )

                elif etype == "tool_skipped":
                    self.current_conversation.add_message(
                        "tool",
                        json.dumps({
                            "tool": event["tool"],
                            "skipped": True,
                            "reason": event.get("reason", ""),
                        }),
                    )

                elif etype == "tool_result":
                    result = event["result"]
                    status = (
                        result.get("status", "success")
                        if isinstance(result, dict)
                        else "success"
                    )
                    result_content = ToolResultFormatter.format_plain(
                        tool=event["tool"],
                        action=event["action"],
                        params=event.get("params", {}),
                        result=result,
                    )
                    self.current_conversation.add_message("tool_result", result_content)
                    logger.info(
                        f"[StreamChatWithMsgs] 工具 {event['tool']}.{event['action']} "
                        f"执行完成 | status={status}"
                    )
                    yield json.dumps({
                        "type": "tool_result",
                        "tool": event["tool"],
                        "action": event["action"],
                        "status": status,
                        "result": result,
                    })

                elif etype == "result":
                    final_result = event["result"]

            if final_result is None:
                logger.warning(
                    "[StreamChatWithMsgs] AgentLoopRunner 未返回 result, 兜底使用 Phase 1 响应"
                )
                final_result = AgentLoopResult(
                    final_text=streamed_text,
                    final_thinking=streamed_thinking,
                    iterations_used=1,
                )

            final_response = final_result.final_text
            thinking = final_result.final_thinking
            if final_result.max_iterations_reached:
                logger.warning(
                    f"[StreamChatWithMsgs] 达到最大工具迭代次数 "
                    f"({self.agent_loop_runner.config.max_iterations})"
                )

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
        if final_response != phase1_text:
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

    async def _generate_topic_for_first_turn(
        self,
        user_input: str,
        model: Optional[str] = None,
        instance=None,
    ) -> Optional[str]:
        """首轮对话的主题生成 — chat() 的两条分支共用.

        Returns 生成的主题; 已存在 / 跳过 (纯图片 / 失败) 时返回 None.
        副作用: 写 self.current_conversation.topic + 持久化到 DB.
        """
        if self.current_conversation.topic:
            return None
        if not all(m.role in ("user", "assistant", "tool", "tool_result")
                   for m in self.current_conversation.messages):
            return None
        first_user = next(
            (m for m in self.current_conversation.messages if m.role == "user"),
            None,
        )
        if not first_user or first_user.image or not first_user.content:
            return None
        try:
            topic = await generate_topic(
                self.router, first_user.content,
                model=model, instance=instance,
            )
            self.current_conversation.set_topic(topic)
            await self.memory.update_conversation_topic(
                self.current_conversation.conversation_id, topic
            )
            logger.info(
                f"[Chat] 已生成对话主题 | conv_id={self.current_conversation.conversation_id} "
                f"| topic={topic!r}"
            )
            return topic
        except Exception as e:
            logger.warning(f"[Chat] 主题生成失败: {e}")
            return None

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