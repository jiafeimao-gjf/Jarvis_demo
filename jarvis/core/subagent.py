# jarvis/core/subagent.py
"""Subagent 模块 — 角色化、可隔离、可并行的子代理.

设计动机
--------
原架构只有一条主对话流 + 工具调用循环 (ChatEngine.stream_chat). 当用户提出
"调研 X / 写代码 / 复审方案" 这类多步任务时, 主 LLM 只能串行执行、上下文
被自己的工具结果污染, 而且无法并行.

Subagent 把"子任务委派"做成一等公民:
  - 多个隔离的子代理 (researcher / coder / reviewer / summarizer ...)
  - 每个子代理有自己的 system prompt + 可见工具子集 + (可选) 不同模型
  - 独立 context, 不污染主对话
  - 编排器支持串行 / 并行 / map-reduce 三种调度

主 LLM 通过 `subagent` 工具调用委派子任务, 编排器收集结果回注主对话.
主代理自身也可以在自己的循环内派生更多子代理 (递归, 默认禁止超过 2 层).
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Any, Callable, Awaitable, TYPE_CHECKING

from jarvis.utils.logger import get_logger

if TYPE_CHECKING:
    from jarvis.services.ai.router import AIRouter
    from jarvis.core.entities import Conversation

logger = get_logger(__name__)


# ── 角色枚举 ───────────────────────────────────────────────────────

class SubagentRole(str, Enum):
    """内置子代理角色."""
    RESEARCHER = "researcher"     # 网络调研、信息收集
    CODER = "coder"               # 代码生成、修改、测试
    REVIEWER = "reviewer"         # 代码/方案复审, 给出修改建议
    SUMMARIZER = "summarizer"     # 长文本摘要、要点提取
    PLANNER = "planner"           # 任务拆解、计划生成
    GENERAL = "general"           # 默认通用代理


class DispatchMode(str, Enum):
    """编排模式."""
    SEQUENTIAL = "sequential"     # 串行: 顺序执行, 下一个能看到上一个的输出
    PARALLEL = "parallel"         # 并行: asyncio.gather, 适合独立子任务
    MAP_REDUCE = "map_reduce"     # 并行执行, 由 reduce_prompt 汇总


# ── 子代理配置 ─────────────────────────────────────────────────────

@dataclass
class SubagentConfig:
    """子代理的运行时配置."""
    role: SubagentRole
    system_prompt: str
    allowed_tools: list[str] = field(default_factory=list)  # 空 = 全部
    model: Optional[str] = None         # None = 跟随主代理
    max_iterations: int = 3             # 单个子代理内部 tool 循环上限
    max_tokens_output: int = 1024
    temperature: float = 0.4
    timeout: float = 120.0              # 总超时 (秒)


@dataclass
class SubagentResult:
    """单个子代理的执行结果."""
    role: SubagentRole
    task: str
    success: bool
    output: str = ""                    # 终态文本输出
    iterations: int = 0                 # 实际工具循环轮数
    tool_calls: list[dict] = field(default_factory=list)
    elapsed_ms: float = 0.0
    error: Optional[str] = None
    sub_session_id: Optional[str] = None  # v3: 独立子会话 ID (主会话可跳转)

    def to_dict(self) -> dict:
        return {
            "role": self.role.value,
            "task": self.task,
            "success": self.success,
            "output": self.output,
            "iterations": self.iterations,
            "tool_calls_count": len(self.tool_calls),
            "elapsed_ms": round(self.elapsed_ms, 1),
            "error": self.error,
            "sub_session_id": self.sub_session_id,
        }


# ── BaseSubagent ───────────────────────────────────────────────────

class BaseSubagent(ABC):
    """子代理抽象基类.

    子类需要实现:
      - default_config() -> SubagentConfig   (角色特定默认值)
      - build_system_prompt(task: str) -> str (任务相关的系统提示)

    v3 新增: 每个调用创建独立子会话 (Conversation), 通过 message_store 持久化.
      - parent_conversation: 父会话 (主对话), 触发本次委派的会话
      - message_store:       MemoryStore 实例, 提供 save_sub_session / get_conversation
      - sub_session:         本次调用的独立子会话 (run() 时创建)
      - sub_session_id:      写入 SubagentResult, 主对话可跳转
    """

    role: SubagentRole = SubagentRole.GENERAL

    def __init__(
        self,
        router: "AIRouter",
        config: Optional[SubagentConfig] = None,
        work_folder: Optional[str] = None,
        parent_conversation: Optional["Conversation"] = None,
        message_store: Optional[Any] = None,
        triggered_by_message_id: Optional[str] = None,
    ):
        self.router = router
        self.config = config or self.default_config()
        self.work_folder = work_folder
        self.parent_conversation = parent_conversation
        self.message_store = message_store
        self.triggered_by_message_id = triggered_by_message_id

    @classmethod
    def default_config(cls) -> SubagentConfig:
        return SubagentConfig(
            role=cls.role,
            system_prompt="You are a helpful AI assistant.",
        )

    @abstractmethod
    def build_system_prompt(self, task: str) -> str:
        """根据任务动态生成 system prompt."""

    def _init_sub_session(self, task: str) -> Optional["Conversation"]:
        """创建独立子会话. 没有 parent/store 时返回 None (单元测试场景)."""
        if self.parent_conversation is None or self.message_store is None:
            return None
        from jarvis.core.entities import Conversation
        sub = Conversation(
            conversation_id=str(uuid.uuid4()),
            user_id=self.parent_conversation.user_id or "",
            topic=f"[{self.role.value}] {task[:40]}",
            parent_conversation_id=self.parent_conversation.conversation_id,
            session_kind="subagent",
            subagent_role=self.role.value,
            subagent_task=task,
            triggered_by_message_id=self.triggered_by_message_id,
            metadata={"mode": "single"},
        )
        logger.debug(
            f"[Subagent {self.role.value}] init sub_session={sub.conversation_id[:8]}... "
            f"parent={self.parent_conversation.conversation_id[:8]}..."
        )
        return sub

    async def _persist_sub_session(self, session: Optional["Conversation"]) -> None:
        """把子会话持久化到 DB."""
        if session is None or self.message_store is None:
            return
        try:
            await self.message_store.save_sub_session(session)
            logger.debug(
                f"[Subagent {self.role.value}] sub_session persisted "
                f"({len(session.messages)} msgs)"
            )
        except Exception as e:
            logger.warning(
                f"[Subagent {self.role.value}] sub_session persist failed: {e}"
            )

    async def run(self, task: str, context: Optional[str] = None) -> SubagentResult:
        """执行子任务. 默认实现: 单轮 LLM 调用 (无工具).

        需要工具循环的子类应重写此方法 (见 ResearcherSubagent).

        v3: 每次调用会创建独立子会话, 记录 user/assistant 消息, 持久化到 DB.
        """
        t0 = time.time()

        # 创建子会话 (如果注入了 parent/store)
        sub_session = self._init_sub_session(task)

        messages = [
            {"role": "system", "content": self.build_system_prompt(task)},
        ]
        if context:
            messages.append({"role": "user", "content": f"[背景上下文]\n{context}"})
        messages.append({"role": "user", "content": task})

        # 记录 user 消息到子会话
        if sub_session is not None:
            from jarvis.core.entities import Message
            user_content = task if not context else f"[背景] {context}\n\n[任务] {task}"
            sub_session.add_message("user", user_content)

        try:
            resp = await asyncio.wait_for(
                self.router.chat(
                    messages,
                    model=self.config.model,
                    stream=False,
                ),
                timeout=self.config.timeout,
            )

            # 记录 assistant 消息到子会话
            if sub_session is not None:
                from jarvis.core.entities import Message
                thinking_text = (
                    resp.thinking if isinstance(getattr(resp, "thinking", ""), str) else ""
                )
                sub_session.add_message(
                    "assistant", resp.content or "", thinking=thinking_text
                )

            await self._persist_sub_session(sub_session)

            return SubagentResult(
                role=self.role,
                task=task,
                success=True,
                output=resp.content,
                iterations=1,
                elapsed_ms=(time.time() - t0) * 1000,
                sub_session_id=sub_session.conversation_id if sub_session else None,
            )
        except Exception as e:
            logger.error(f"[Subagent {self.role.value}] failed: {e}")

            # 即使失败也持久化子会话 (记录失败状态)
            if sub_session is not None:
                from jarvis.core.entities import Message
                sub_session.add_message("assistant", f"[执行失败] {e}")
            await self._persist_sub_session(sub_session)

            return SubagentResult(
                role=self.role,
                task=task,
                success=False,
                error=str(e),
                elapsed_ms=(time.time() - t0) * 1000,
                sub_session_id=sub_session.conversation_id if sub_session else None,
            )


# ── 内置子代理实现 ─────────────────────────────────────────────────

class ResearcherSubagent(BaseSubagent):
    role = SubagentRole.RESEARCHER

    def build_system_prompt(self, task: str) -> str:
        return (
            "你是一名专业研究员. 任务:\n"
            f"{task}\n\n"
            "要求:\n"
            "1. 客观、可验证, 引用来源 (URL/标题)\n"
            "2. 多角度对比, 区分事实与推测\n"
            "3. 用结构化要点回复 (Markdown), 不要冗长\n"
            "4. 如果信息不足, 明确说明, 不要编造"
        )


class CoderSubagent(BaseSubagent):
    role = SubagentRole.CODER

    def build_system_prompt(self, task: str) -> str:
        return (
            "你是一名严谨的软件工程师. 任务:\n"
            f"{task}\n\n"
            "要求:\n"
            "1. 先思考 1-2 句实现思路, 再写代码\n"
            "2. 代码自包含, 可直接运行, 加必要注释\n"
            "3. 边界情况 (空输入、异常) 简短提示\n"
            "4. 最后用 markdown 代码块包裹"
        )


class ReviewerSubagent(BaseSubagent):
    role = SubagentRole.REVIEWER

    def build_system_prompt(self, task: str) -> str:
        return (
            "你是一名严格的代码/方案评审员. 任务:\n"
            f"{task}\n\n"
            "要求:\n"
            "1. 按 优点 / 问题 / 建议 三段式回复\n"
            "2. 问题必须具体到行/段/概念, 不要泛泛而谈\n"
            "3. 给出可执行的修改建议, 优先级排序\n"
            "4. 如无明显问题, 直接说明 'PASS', 不要硬挑刺"
        )


class SummarizerSubagent(BaseSubagent):
    role = SubagentRole.SUMMARIZER

    def build_system_prompt(self, task: str) -> str:
        return (
            "你是一名专业的文本摘要员. 任务:\n"
            f"{task}\n\n"
            "要求:\n"
            "1. 保留关键事实、数据、结论\n"
            "2. 删除冗余和客套话\n"
            "3. 输出结构化 (主题 / 关键点 / 数据 / 待办), Markdown\n"
            "4. 长度不超过原文 25%"
        )


class PlannerSubagent(BaseSubagent):
    role = SubagentRole.PLANNER

    def build_system_prompt(self, task: str) -> str:
        return (
            "你是一名任务规划师. 任务:\n"
            f"{task}\n\n"
            "要求:\n"
            "1. 拆解为 3-7 个有序子步骤\n"
            "2. 每个步骤标注: 输入、产出、依赖、风险\n"
            "3. 最后给出验收标准 (Definition of Done)\n"
            "4. 不要写代码, 只做规划"
        )


class GeneralSubagent(BaseSubagent):
    role = SubagentRole.GENERAL

    def build_system_prompt(self, task: str) -> str:
        return (
            "你是一名通用 AI 助手, 在一个独立、隔离的上下文中执行子任务.\n"
            f"任务:\n{task}\n\n"
            "请专注完成此任务, 输出简洁."
        )


# ── 工厂 ───────────────────────────────────────────────────────────

_ROLE_REGISTRY: dict[SubagentRole, type[BaseSubagent]] = {
    SubagentRole.RESEARCHER: ResearcherSubagent,
    SubagentRole.CODER: CoderSubagent,
    SubagentRole.REVIEWER: ReviewerSubagent,
    SubagentRole.SUMMARIZER: SummarizerSubagent,
    SubagentRole.PLANNER: PlannerSubagent,
    SubagentRole.GENERAL: GeneralSubagent,
}


def create_subagent(
    role: SubagentRole | str,
    router: "AIRouter",
    work_folder: Optional[str] = None,
    config_overrides: Optional[dict] = None,
    parent_conversation: Optional["Conversation"] = None,
    message_store: Optional[Any] = None,
    triggered_by_message_id: Optional[str] = None,
) -> BaseSubagent:
    """工厂方法: 按角色构造子代理 (v3 支持 parent / store)."""
    if isinstance(role, str):
        try:
            role = SubagentRole(role)
        except ValueError:
            logger.warning(f"[Subagent] unknown role {role!r}, using GENERAL")
            role = SubagentRole.GENERAL

    cls = _ROLE_REGISTRY.get(role, GeneralSubagent)
    agent = cls(
        router=router,
        work_folder=work_folder,
        parent_conversation=parent_conversation,
        message_store=message_store,
        triggered_by_message_id=triggered_by_message_id,
    )

    if config_overrides:
        for k, v in config_overrides.items():
            if hasattr(agent.config, k):
                setattr(agent.config, k, v)
    return agent


# ── Orchestrator ───────────────────────────────────────────────────

@dataclass
class DispatchRequest:
    """编排请求 (单子任务)."""
    role: SubagentRole
    task: str
    context: Optional[str] = None
    config_overrides: Optional[dict] = None


@dataclass
class DispatchBatchResult:
    """一批 DispatchRequest 的合并结果."""
    mode: DispatchMode
    results: list[SubagentResult]
    reduced_output: Optional[str] = None   # MAP_REDUCE 模式下的汇总文本

    @property
    def all_success(self) -> bool:
        return all(r.success for r in self.results)

    def to_dict(self) -> dict:
        return {
            "mode": self.mode.value,
            "all_success": self.all_success,
            "count": len(self.results),
            "results": [r.to_dict() for r in self.results],
            "reduced_output": self.reduced_output,
        }


class SubagentOrchestrator:
    """子代理编排器.

    用法:
        orch = SubagentOrchestrator(
            router=chat_engine.router,
            parent_conversation=chat_engine.current_conversation,  # v3
            message_store=memory_store,                             # v3
        )
        result = await orch.run_one(SubagentRole.RESEARCHER, "...")
        batch = await orch.run_batch(
            DispatchMode.PARALLEL,
            [
                DispatchRequest(SubagentRole.RESEARCHER, "..."),
                DispatchRequest(SubagentRole.SUMMARIZER, "..."),
            ],
        )

    v3: 注入 parent_conversation 和 message_store 后, 每个 subagent 自动创建独立
        子会话, 主对话可通过 sub_session_id 跳转查看完整 trace.
    """

    def __init__(
        self,
        router: "AIRouter",
        work_folder: Optional[str] = None,
        reducer: Optional[Callable[[list[SubagentResult]], Awaitable[str]]] = None,
        parent_conversation: Optional["Conversation"] = None,
        message_store: Optional[Any] = None,
        triggered_by_message_id: Optional[str] = None,
    ):
        self.router = router
        self.work_folder = work_folder
        self.parent_conversation = parent_conversation
        self.message_store = message_store
        self.triggered_by_message_id = triggered_by_message_id
        # 默认 reducer: 把多个结果拼起来, 让 LLM 二次综合
        self.reducer = reducer or self._default_reducer

    @staticmethod
    async def _default_reducer(results: list[SubagentResult]) -> str:
        parts = []
        for i, r in enumerate(results, 1):
            status = "OK" if r.success else f"FAIL({r.error})"
            parts.append(
                f"### [{i}] {r.role.value} — {status}\n"
                f"**任务**: {r.task}\n\n"
                f"**输出**:\n{r.output or '(无)'}\n"
            )
        return "\n\n".join(parts)

    async def run_one(
        self,
        role: SubagentRole | str,
        task: str,
        context: Optional[str] = None,
        config_overrides: Optional[dict] = None,
    ) -> SubagentResult:
        agent = create_subagent(
            role=role,
            router=self.router,
            work_folder=self.work_folder,
            config_overrides=config_overrides,
            parent_conversation=self.parent_conversation,
            message_store=self.message_store,
            triggered_by_message_id=self.triggered_by_message_id,
        )
        logger.info(
            f"[Orchestrator] dispatching {agent.role.value}: {task[:80]!r}"
        )
        return await agent.run(task=task, context=context)

    async def run_batch(
        self,
        mode: DispatchMode,
        requests: list[DispatchRequest],
        reduce_prompt: Optional[str] = None,
    ) -> DispatchBatchResult:
        if not requests:
            return DispatchBatchResult(mode=mode, results=[])

        if mode == DispatchMode.SEQUENTIAL:
            results: list[SubagentResult] = []
            # 串行: 下一个任务可看到前面所有输出作为 context
            prior_context: list[str] = []
            for req in requests:
                ctx = req.context or ""
                if prior_context:
                    ctx = (
                        ctx + "\n\n[先前子代理输出]\n" + "\n---\n".join(prior_context)
                    ).strip()
                results.append(
                    await self.run_one(req.role, req.task, ctx, req.config_overrides)
                )
                if results[-1].output:
                    prior_context.append(
                        f"[{results[-1].role.value}] {results[-1].output}"
                    )
            return DispatchBatchResult(mode=mode, results=results)

        if mode == DispatchMode.PARALLEL:
            results = await asyncio.gather(
                *[
                    self.run_one(r.role, r.task, r.context, r.config_overrides)
                    for r in requests
                ],
                return_exceptions=False,
            )
            return DispatchBatchResult(mode=mode, results=list(results))

        # MAP_REDUCE
        results = await asyncio.gather(
            *[
                self.run_one(r.role, r.task, r.context, r.config_overrides)
                for r in requests
            ]
        )
        reduced = await self.reducer(list(results))
        # 如果用户提供了 reduce_prompt, 让 LLM 基于汇总再做一次综合
        if reduce_prompt:
            try:
                messages = [
                    {"role": "system", "content": (
                        "你是信息汇总员. 给定多个子代理的输出, 请按用户要求综合."
                    )},
                    {"role": "user", "content": (
                        f"[汇总要求]\n{reduce_prompt}\n\n"
                        f"[子代理输出]\n{reduced}"
                    )},
                ]
                resp = await self.router.chat(messages, stream=False)
                reduced = resp.content
            except Exception as e:
                logger.warning(f"[Orchestrator] reduce LLM call failed: {e}")
        return DispatchBatchResult(
            mode=mode, results=list(results), reduced_output=reduced
        )