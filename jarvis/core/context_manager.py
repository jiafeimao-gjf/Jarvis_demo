# jarvis/core/context_manager.py
"""上下文管理 — token 预算、滑动窗口、对话压缩、记忆增强.

设计动机
--------
原 chat_engine 在三处 (chat / stream_chat / stream_chat_with_messages) 都硬编码
`get_history(limit=10)`。当对话变长时:
  1. 早期消息永久丢失, LLM 看不见上下文
  2. 没有 token 预算, system_prompt + 10 条消息可能直接撑爆小模型 context
  3. tool/tool_result 消息无清理, 越聊越长
  4. 长对话下记忆检索完全靠 hash embedding (memory_store.simple_embed)

ContextManager 把"如何从对话历史 + 记忆中构建送入 LLM 的消息列表"集中成
可插拔的策略 (Strategy Pattern), 默认 HybridStrategy:
    system_prompt
      ├── 角色/能力/技能 (workspace/prompts/*.md + skills)
      ├── 相关记忆 (memory.retrieve)
      └── 对话历史 (按 token 预算裁剪: 早期摘要 + 最近原文)

导出
----
- ContextManager            : 入口, ChatEngine 调 build_messages()
- CompactionStrategy (ABC)  : 压缩策略接口
- SlidingWindowStrategy     : 仅按 token 保留最近 N 条
- SummarizationStrategy     : 早期消息压缩为一段摘要
- HybridStrategy (default)  : 摘要 + 滑动窗口 + 记忆增强
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Any

from jarvis.services.ai.models import MODELS
from jarvis.utils.logger import get_logger

logger = get_logger(__name__)


# ── Token counting ─────────────────────────────────────────────────
# 尝试用 tiktoken, 否则回退到字符估算 (1 token ≈ 4 chars, 英文偏多).
_tiktoken_enc = None
try:
    import tiktoken
    _tiktoken_enc = tiktoken.get_encoding("cl100k_base")
except Exception:
    pass


def count_tokens(text: str) -> int:
    """粗略估算 token 数. 优先 tiktoken, 否则 4 字符/token."""
    if not text:
        return 0
    if _tiktoken_enc is not None:
        try:
            return len(_tiktoken_enc.encode(text))
        except Exception:
            pass
    return max(1, len(text) // 4)


def messages_tokens(messages: list[dict]) -> int:
    """估算一组消息的 token 数 (每条消息额外 +4 角色/分隔开销)."""
    total = 0
    for m in messages:
        total += 4  # role + separators
        content = m.get("content")
        if isinstance(content, str):
            total += count_tokens(content)
        elif isinstance(content, list):
            # Anthropic-style content_blocks
            for blk in content:
                if isinstance(blk, dict):
                    txt = blk.get("text") or blk.get("thinking") or ""
                    if isinstance(txt, str):
                        total += count_tokens(txt)
                    # tool_use input 也算上
                    inp = blk.get("input")
                    if isinstance(inp, dict):
                        total += count_tokens(json.dumps(inp, ensure_ascii=False))
        elif content is not None:
            total += count_tokens(str(content))
    return total


# ── Configuration ─────────────────────────────────────────────────

@dataclass
class ContextBudget:
    """一个对话轮的 token 预算配置."""
    max_context_window: int = 8192      # 模型 context_window, 决定总预算
    reserve_for_output: int = 1024     # 留给 LLM 输出
    reserve_for_system: int = 0        # system_prompt 占用的, 动态测量
    reserve_for_memory: int = 800      # 相关记忆注入预算
    min_keep_recent: int = 4           # 无论如何保留最近 N 条原文

    @property
    def available_for_history(self) -> int:
        """对话历史可用的 token."""
        return max(
            512,
            self.max_context_window - self.reserve_for_output
            - self.reserve_for_system - self.reserve_for_memory
        )


# ── Strategy interface ─────────────────────────────────────────────

@dataclass
class CompactionResult:
    """压缩策略返回: 注入到 LLM 的消息列表 (system 已包含)."""
    messages: list[dict]              # system + (可选摘要) + 历史 + 当前用户
    summary_added: bool = False       # 是否注入了早期消息摘要
    dropped_count: int = 0            # 被丢弃的早期消息数
    token_estimate: int = 0           # 估算的总 token


class CompactionStrategy(ABC):
    """对话历史压缩策略 (Strategy Pattern)."""

    @abstractmethod
    async def compact(
        self,
        history: list[dict],           # 来自 conversation.get_history()
        budget: ContextBudget,
        summarizer: Optional["Callable[[list[dict]], Any]"] = None,
    ) -> CompactionResult:
        """从 history 中选出要在本轮送入 LLM 的部分.

        summarizer: 可选的可调用对象, 接收消息列表, 返回压缩后的字符串
                    (None 时策略降级, 不做摘要)
        """


# ── Concrete strategies ────────────────────────────────────────────

class SlidingWindowStrategy(CompactionStrategy):
    """最简单的策略: 从尾部往前保留, 凑满预算为止."""

    def __init__(self, max_recent: int = 20):
        self.max_recent = max_recent

    async def compact(self, history, budget, summarizer=None):
        recent = history[-self.max_recent:]
        result_msgs = list(recent)
        dropped = max(0, len(history) - self.max_recent)

        # 如果还超预算, 再从前端开始丢
        while (
            messages_tokens(result_msgs) > budget.available_for_history
            and len(result_msgs) > budget.min_keep_recent
        ):
            result_msgs.pop(0)
            dropped += 1

        return CompactionResult(
            messages=result_msgs,
            summary_added=False,
            dropped_count=dropped,
            token_estimate=messages_tokens(result_msgs),
        )


class SummarizationStrategy(CompactionStrategy):
    """早期消息用 LLM 摘要, 近期消息保留原文."""

    def __init__(self, trigger_ratio: float = 0.7):
        # history token 超过 budget * trigger_ratio 才触发摘要
        self.trigger_ratio = trigger_ratio

    async def compact(self, history, budget, summarizer=None):
        total = messages_tokens(history)
        if total <= budget.available_for_history:
            return CompactionResult(
                messages=list(history),
                summary_added=False,
                dropped_count=0,
                token_estimate=total,
            )

        # 保留尾部, 把前段丢给 summarizer
        keep_from = len(history)
        # 先按 budget 倒推: 至少留 N 条原文
        kept: list[dict] = []
        for msg in reversed(history):
            kept.insert(0, msg)
            if (
                len(kept) >= budget.min_keep_recent
                and messages_tokens(kept) > budget.available_for_history * 0.6
            ):
                break
        dropped_head = history[: len(history) - len(kept)]

        if summarizer is None or not dropped_head:
            # 没有 summarizer 就退化成滑动窗口
            kept = history[-budget.min_keep_recent:]
            dropped_head = history[: -len(kept)] if kept else history
            return CompactionResult(
                messages=kept,
                summary_added=False,
                dropped_count=len(dropped_head),
                token_estimate=messages_tokens(kept),
            )

        try:
            summary_text = await summarizer(dropped_head)
        except Exception as e:
            logger.warning(f"[Context] summarizer failed: {e}, falling back to window")
            kept = history[-budget.min_keep_recent:]
            return CompactionResult(
                messages=kept,
                summary_added=False,
                dropped_count=len(history) - len(kept),
                token_estimate=messages_tokens(kept),
            )

        summary_msg = {
            "role": "system",
            "content": (
                "[历史对话摘要 — 以下是本对话早期内容的压缩, "
                "请把它当作背景理解, 不要重复其中结论]\n\n"
                + (summary_text or "")
            ),
        }
        return CompactionResult(
            messages=[summary_msg, *kept],
            summary_added=True,
            dropped_count=len(dropped_head),
            token_estimate=messages_tokens([summary_msg]) + messages_tokens(kept),
        )


class HybridStrategy(CompactionStrategy):
    """默认策略 = 记忆增强 + 摘要压缩 + 滑动窗口 三段组合."""

    def __init__(self):
        self._inner = SummarizationStrategy()

    async def compact(self, history, budget, summarizer=None):
        return await self._inner.compact(history, budget, summarizer)


# ── ContextManager — 入口 ──────────────────────────────────────────

class ContextManager:
    """构建送入 LLM 的消息列表 (system + 记忆 + 历史).

    用法 (ChatEngine 集成):
        ctx = ContextManager()
        messages = await ctx.build_messages(
            system_prompt=...,
            history=[...],          # 已序列化的 dict 列表
            current_user_input=...,
            memory_retriever=memory.retrieve,
            summarizer=llm_summarizer,   # 可选, 用 LLM 摘要早期消息
            model_id="qwen3:4b",
        )
        # messages 即可送入 router.chat(...)

    与 ContextCompressor 的关系:
      - ContextManager     : per-call, 决定本次送哪些消息
      - ContextCompressor  : per-conversation, 决定是否把历史压缩为摘要
        (通过可选的 `compressor` 参数接入, 见 build_messages 里的可选步骤)
    """

    DEFAULT_BUDGET = ContextBudget()

    # Anthropic /v1/messages 严格只接受 system/user/assistant 三种 role.
    # 其他 role (tool/tool_result 等) 是工具运行期的中间表示, 无法在不丢失
    # 上下文的前提下回放 — 必须从 history 中剥离, 否则 LLM 代理会 4xx.
    HISTORY_ALLOWED_ROLES = {"system", "user", "assistant"}

    # PR4: 不同 provider 对 history 的容错策略不同
    # - STRICT: 严格剥离所有非 {system,user,assistant} role + 空 content
    #          (Anthropic / MiniMax 严格模式, 错传 tool_result 会 4xx)
    # - LENIENT: 保留 user role 的 tool_result blocks (结构化)
    #          (OpenAI 兼容, 因为后续 agent_loop 会用 provider_protocol 决定 tool_result 形态,
    #           但若 user msg.content 是 list 含 tool_result 块, OpenAI 会拒绝;
    #           默认仍走 STRICT, 真正结构化 tool_result 由 AgentLoopRunner 在 Phase 2 注入)
    HISTORY_REPLAY_POLICY_DEFAULT = "strict"

    @classmethod
    def _sanitize_history(cls, history: list[dict]) -> tuple[list[dict], int]:
        """PR4 兼容入口 — 等价于 policy=STRICT."""
        return cls._normalize_history(history, policy="strict")

    @classmethod
    def _normalize_history(
        cls, history: list[dict], policy: Optional[str] = None
    ) -> tuple[list[dict], int]:
        """PR4: 按 policy 规整 history.

        policy:
          - "strict"   (默认): 仅保留 {system, user, assistant}; 跳过空 content;
                             跳过非 dict 项
          - "lenient": 保留所有 role; 仅跳过非 dict / 完全空字符串 content;
                       让 caller 自行决定能否回放
        """
        cleaned: list[dict] = []
        dropped = 0
        use_strict = (policy or cls.HISTORY_REPLAY_POLICY_DEFAULT).lower() == "strict"
        for m in history or []:
            if not isinstance(m, dict):
                dropped += 1
                continue
            role = m.get("role")
            if use_strict and role not in cls.HISTORY_ALLOWED_ROLES:
                dropped += 1
                continue
            content = m.get("content")
            # STRICT: 空字符串 / None 都不要
            # LENIENT: 保留 list 形态 (含 tool_result 块), 只跳过完全空字符串
            if content is None:
                if use_strict:
                    dropped += 1
                    continue
            elif isinstance(content, str) and not content.strip():
                dropped += 1
                continue
            cleaned.append(m)
        return cleaned, dropped

    def __init__(
        self,
        strategy: Optional[CompactionStrategy] = None,
        compressor: Optional[Any] = None,  # ContextCompressor 实例, 避免循环导入
    ):
        self.strategy = strategy or HybridStrategy()
        self.compressor = compressor  # 可选: per-conversation 自动压缩

    @staticmethod
    def context_window_for(model_id: Optional[str]) -> int:
        """从 MODELS 注册表查 context_window, 找不到回退默认."""
        if not model_id:
            return ContextManager.DEFAULT_BUDGET.max_context_window
        info = MODELS.get(model_id)
        if info and info.context_window:
            return info.context_window
        return ContextManager.DEFAULT_BUDGET.max_context_window

    @staticmethod
    def budget_for(
        model_id: Optional[str],
        reserve_for_output: int = 1024,
        reserve_for_memory: int = 800,
        min_keep_recent: int = 4,
    ) -> ContextBudget:
        return ContextBudget(
            max_context_window=ContextManager.context_window_for(model_id),
            reserve_for_output=reserve_for_output,
            reserve_for_memory=reserve_for_memory,
            min_keep_recent=min_keep_recent,
        )

    async def build_messages(
        self,
        system_prompt: str,
        history: list[dict],
        current_user_input: Optional[str] = None,
        current_user_image: Optional[str] = None,
        memory_retriever: Optional[Any] = None,
        summarizer: Optional[Any] = None,
        model_id: Optional[str] = None,
        memory_top_k: int = 3,
        budget: Optional[ContextBudget] = None,
        conversation: Optional[Any] = None,  # Conversation 对象, 启用 compressor 时需要
    ) -> dict:
        """构建本轮送入 LLM 的消息列表. 返回 dict 便于扩展.

        返回结构:
            {
              "messages": [{"role": ..., "content": ...}, ...],
              "stats": {
                "history_in": <int>,
                "history_out": <int>,
                "dropped": <int>,
                "summary_added": <bool>,
                "memory_chunks": <int>,
                "tokens_estimate": <int>,
                "budget_available": <int>,
                "compressed": <bool>,  # 本轮是否触发了 compressor
              }
            }

        如果传入了 `compressor` (构造时) + `conversation` (调用时):
          - 在压缩历史之前先调 compressor.maybe_compress, 修改 conversation.messages
          - 再用更新后的 history 继续构建
        """
        budget = budget or self.budget_for(model_id)

        # 0a) 剔除 history 里不能回放的中间角色 (tool / tool_result 等)
        # — 详见 HISTORY_ALLOWED_ROLES 注释.
        history, dropped_tool_msgs = self._sanitize_history(history)
        if dropped_tool_msgs:
            logger.info(
                f"[Context] filtered {dropped_tool_msgs} non-replayable "
                f"tool/tool_result messages from history"
            )

        # 0) 可选: 触发 per-conversation 自动压缩
        compressed = False
        if self.compressor is not None and conversation is not None:
            try:
                result = await self.compressor.maybe_compress(
                    conversation=conversation,
                    model_id=model_id,
                )
                if result is not None:
                    # compressor 已修改 conversation.messages, 重新读 history
                    history = [
                        {"role": m.role, "content": m.content}
                        for m in conversation.messages
                    ]
                    history, dropped2 = self._sanitize_history(history)
                    if dropped2:
                        logger.info(
                            f"[Context] filtered {dropped2} non-replayable "
                            f"messages after compressor refresh"
                        )
                    compressed = True
                    logger.info(
                        f"[Context] per-conversation 压缩完成 | "
                        f"dropped={result.dropped_count} "
                        f"ratio={result.compression_ratio:.2f}x"
                    )
            except Exception as e:
                logger.warning(f"[Context] compressor 调用失败: {e}")
        # 动态修正 reserve_for_system: 实际 system_prompt 用多少算多少
        sys_tokens = count_tokens(system_prompt)
        budget.reserve_for_system = sys_tokens

        # 1) 检索相关记忆 (注入到 system_prompt 末尾)
        memory_chunks: list[str] = []
        if memory_retriever is not None:
            query = current_user_input or (history[-1].get("content", "") if history else "")
            if query:
                try:
                    memories = await memory_retriever(query, memory_top_k)
                    for m in memories or []:
                        c = m.get("content") if isinstance(m, dict) else None
                        if c:
                            memory_chunks.append(c)
                except Exception as e:
                    logger.warning(f"[Context] memory retrieve failed: {e}")

        if memory_chunks:
            memory_block = "\n相关记忆:\n" + "\n".join(f"- {c}" for c in memory_chunks)
            system_prompt = system_prompt + memory_block

        # 2) 压缩历史
        result = await self.strategy.compact(
            history=history,
            budget=budget,
            summarizer=summarizer,
        )

        # 3) 拼接最终消息列表
        messages: list[dict] = [{"role": "system", "content": system_prompt}]
        messages.extend(result.messages)
        if current_user_input is not None:
            user_msg: dict = {"role": "user", "content": current_user_input}
            if current_user_image:
                user_msg["image"] = current_user_image
            messages.append(user_msg)

        return {
            "messages": messages,
            "stats": {
                "history_in": len(history),
                "history_out": len(result.messages),
                "dropped": result.dropped_count,
                "summary_added": result.summary_added,
                "memory_chunks": len(memory_chunks),
                "tokens_estimate": messages_tokens(messages),
                "budget_available": budget.available_for_history,
                "compressed": compressed,
            },
        }