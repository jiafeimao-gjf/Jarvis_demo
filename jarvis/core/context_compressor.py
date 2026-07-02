# jarvis/core/context_compressor.py
"""上下文自动压缩 — 监控 token 用量, 超阈值时调 LLM 摘要早期消息.

设计动机
--------
ContextManager 的 SummarizationStrategy 已经能压缩, 但有两个问题:
  1. 当前 ChatEngine 没有传 summarizer, 所以策略降级为滑动窗口, 没有真摘要
  2. 没有"何时触发"的明确判断 — 每次 build_messages 都跑一次测量
  3. 没有 per-conversation 状态 — 反复触发的冷却/统计缺失

ContextCompressor 解决上述问题:
  - 主动测量: 接收一个 Conversation, 算出当前 token 用量和阈值比
  - 阈值触发: usage.ratio > threshold (默认 0.75) 才压缩, 避免无谓调用
  - 真 LLM 摘要: 通过 AIRouter 调一次 LLM 总结早期消息
  - 状态持久: 把摘要 + 近期原文写回 Conversation 对象, 持久化到 DB
  - 冷却: 同一对话短时间内不重复触发 (默认 30s)
  - 可观测: 每次压缩都返回 CompressedContext 用于日志/监控

与 ContextManager 的分工:
  - ContextManager      : 每次 LLM 调用前, 决定本次送哪些消息 (短期, per-call)
  - ContextCompressor   : 每轮对话后, 决定是否压缩历史 (长期, per-conversation)
"""
from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Any, TYPE_CHECKING

from jarvis.core.context_manager import (
    ContextBudget,
    count_tokens,
    messages_tokens,
)
from jarvis.utils.logger import get_logger

if TYPE_CHECKING:
    from jarvis.core.entities import Conversation
    from jarvis.services.ai.router import AIRouter

logger = get_logger(__name__)


# ── 数据类 ─────────────────────────────────────────────────────────

@dataclass
class ContextUsage:
    """一次对话当前上下文的用量快照."""
    total_tokens: int
    budget_tokens: int
    threshold_tokens: int
    message_count: int

    @property
    def ratio(self) -> float:
        return self.total_tokens / max(self.budget_tokens, 1)

    @property
    def over_threshold(self) -> bool:
        return self.total_tokens >= self.threshold_tokens

    def to_dict(self) -> dict:
        return {
            "total_tokens": self.total_tokens,
            "budget_tokens": self.budget_tokens,
            "threshold_tokens": self.threshold_tokens,
            "ratio": round(self.ratio, 3),
            "message_count": self.message_count,
            "over_threshold": self.over_threshold,
        }


@dataclass
class CompressedContext:
    """一次压缩的结果."""
    conversation_id: str
    summary: str                       # LLM 生成的早期摘要
    kept_messages: list[dict]          # 保留的近期原文 (dict 形式)
    dropped_count: int                 # 被摘要覆盖的消息数
    before_tokens: int                 # 压缩前总 token
    after_tokens: int                  # 压缩后总 token
    compression_ratio: float           # before / after
    triggered_at: datetime = field(default_factory=datetime.now)
    trigger_reason: str = "threshold"  # threshold / manual / scheduled
    elapsed_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "conversation_id": self.conversation_id,
            "summary_len": len(self.summary),
            "dropped_count": self.dropped_count,
            "kept_count": len(self.kept_messages),
            "before_tokens": self.before_tokens,
            "after_tokens": self.after_tokens,
            "compression_ratio": round(self.compression_ratio, 2),
            "triggered_at": self.triggered_at.isoformat(),
            "trigger_reason": self.trigger_reason,
            "elapsed_ms": round(self.elapsed_ms, 1),
        }


# ── Trigger 策略 ───────────────────────────────────────────────────

class CompressionTrigger(ABC):
    """决定何时触发压缩的策略接口."""

    @abstractmethod
    def should_compress(self, usage: ContextUsage) -> bool:
        """基于用量快照判断是否触发压缩."""

    @abstractmethod
    def describe(self) -> str:
        """人类可读的策略描述 (用于日志)."""


class ThresholdTrigger(CompressionTrigger):
    """简单阈值触发: usage.ratio >= threshold 时触发.

    默认 0.75 表示 context 用到 75% 时开始压缩, 留 25% 给后续对话 + 输出.
    """

    def __init__(self, threshold: float = 0.75):
        if not 0 < threshold <= 1.0:
            raise ValueError(f"threshold 必须在 (0, 1], 得到 {threshold}")
        self.threshold = threshold

    def should_compress(self, usage: ContextUsage) -> bool:
        return usage.ratio >= self.threshold

    def describe(self) -> str:
        return f"ThresholdTrigger(threshold={self.threshold})"


class AdaptiveTrigger(CompressionTrigger):
    """自适应触发: 结合绝对阈值 + 增长斜率.

    在以下任一条件满足时触发:
      - 用量 >= 绝对阈值 (e.g., 0.75)
      - 距离上次压缩 token 增长 >= 增长阈值 (e.g., 1500 tokens)
    """

    def __init__(
        self,
        threshold: float = 0.75,
        growth_threshold_tokens: int = 1500,
    ):
        self.threshold = threshold
        self.growth_threshold_tokens = growth_threshold_tokens
        self._last_tokens: dict[str, int] = {}  # conv_id -> last seen tokens

    def should_compress(self, usage: ContextUsage) -> bool:
        # 条件 1: 总量超阈值
        if usage.ratio >= self.threshold:
            return True
        # 条件 2: 增长过快 (仅在同一对话内有效)
        conv_id = usage_to_conv_id(usage)  # 见下方 helper
        prev = self._last_tokens.get(conv_id)
        if prev is not None and (usage.total_tokens - prev) >= self.growth_threshold_tokens:
            return True
        return False

    def update_last_tokens(self, conv_id: str, total_tokens: int):
        self._last_tokens[conv_id] = total_tokens

    def describe(self) -> str:
        return (
            f"AdaptiveTrigger(threshold={self.threshold}, "
            f"growth_threshold={self.growth_threshold_tokens})"
        )


def usage_to_conv_id(usage: ContextUsage) -> str:
    """从 usage 反查 conv_id — 当前 ContextUsage 不含 conv_id, 走 fallback 0.

    真实场景中由调用方在 maybe_compress 里显式传入 conv_id, 这里是占位.
    """
    return getattr(usage, "_conv_id", "")


# ── LLM 摘要器 ────────────────────────────────────────────────────

SUMMARY_SYSTEM_PROMPT = """你是一名对话历史压缩员. 给定一段早期的对话消息列表, 你的任务是:

1. 提取关键事实、数据、结论、用户偏好、待办事项
2. 删除寒暄、客套、重复内容
3. 用 Markdown 结构化输出 (主题 / 关键点 / 数据 / 待办)
4. 用第三人称客观陈述, 不引入新信息, 不解释"这是摘要"
5. 长度控制在原文的 20-30%

只返回摘要正文, 不要任何前缀说明."""


async def default_summarize(
    router: "AIRouter",
    messages: list[dict],
    model: Optional[str] = None,
    max_tokens: int = 800,
) -> str:
    """调一次 LLM 总结给定消息列表.

    Args:
        router: AIRouter 实例
        messages: 待摘要的消息列表 (dict 形式, 含 role/content)
        model: 可选模型 ID, 默认跟随主模型
        max_tokens: 摘要输出上限

    Returns:
        摘要字符串. 失败时返回 "".
    """
    # 构造摘要输入: 把消息列表格式化成可读文本
    lines: list[str] = []
    for m in messages:
        role = m.get("role", "unknown")
        content = m.get("content", "")
        if isinstance(content, list):  # Anthropic blocks
            content = " ".join(
                blk.get("text", "") for blk in content
                if isinstance(blk, dict) and blk.get("type") == "text"
            )
        if not content:
            continue
        lines.append(f"[{role}] {content[:500]}{'...' if len(content) > 500 else ''}")

    user_prompt = "以下是一段对话历史, 请按要求生成压缩摘要:\n\n" + "\n".join(lines)

    try:
        resp = await router.chat(
            messages=[
                {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            model=model,
            stream=False,
        )
        return (resp.content or "").strip()
    except Exception as e:
        logger.warning(f"[Compressor] LLM 摘要失败: {e}")
        return ""


# ── ContextCompressor 主体 ─────────────────────────────────────────

class ContextCompressor:
    """异步、自动的上下文压缩器.

    用法:
        compressor = ContextCompressor(
            router=chat_engine.router,
            trigger=ThresholdTrigger(threshold=0.75),
            keep_recent=4,
        )

        # 在 ChatEngine 里每轮对话后调用:
        result = await compressor.maybe_compress(
            conversation=self.current_conversation,
            model_id=model,
        )
        if result:
            logger.info(f"compressed: {result.to_dict()}")

    设计要点:
      - maybe_compress 是幂等的, 无副作用时返回 None
      - 不修改外部状态除非真的压缩了
      - 冷却机制: 同一对话 30s 内只压缩一次
      - 持久化: 通过 Conversation 对象自身的 save 方法 (依赖 chat_engine 注入)
    """

    DEFAULT_COOLDOWN_SECONDS = 30.0
    DEFAULT_KEEP_RECENT = 4
    DEFAULT_MIN_MESSAGES = 6  # 至少 6 条消息才值得压缩

    def __init__(
        self,
        router: "AIRouter",
        trigger: Optional[CompressionTrigger] = None,
        keep_recent: int = DEFAULT_KEEP_RECENT,
        cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
        min_messages: int = DEFAULT_MIN_MESSAGES,
        persist_fn: Optional[Any] = None,  # async (conv) -> bool
        summarizer: Optional[Any] = None,  # async (router, msgs, model) -> str
    ):
        self.router = router
        self.trigger = trigger or ThresholdTrigger()
        self.keep_recent = keep_recent
        self.cooldown_seconds = cooldown_seconds
        self.min_messages = min_messages
        self.persist_fn = persist_fn
        self.summarizer = summarizer or default_summarize

        # per-conversation 状态
        self._last_compress_at: dict[str, float] = {}
        self._compress_count: dict[str, int] = {}

        logger.info(f"[Compressor] init | trigger={self.trigger.describe()} "
                    f"keep_recent={keep_recent} cooldown={cooldown_seconds}s "
                    f"min_messages={min_messages}")

    # ── 测量 ──────────────────────────────────────────────────────

    def measure(
        self,
        conversation: "Conversation",
        model_id: Optional[str] = None,
    ) -> ContextUsage:
        """测量一个对话当前的 token 用量."""
        from jarvis.core.context_manager import ContextManager
        budget = ContextManager.budget_for(model_id)
        # 把 budget_tokens 设为完整 context window (不只是 history 预算),
        # 因为压缩判断要基于"整个窗口已用多少"
        total = messages_tokens([
            {"role": m.role, "content": m.content} for m in conversation.messages
        ])
        return ContextUsage(
            total_tokens=total,
            budget_tokens=budget.max_context_window,
            threshold_tokens=int(budget.max_context_window * self._trigger_ratio()),
            message_count=len(conversation.messages),
        )

    def _trigger_ratio(self) -> float:
        if isinstance(self.trigger, ThresholdTrigger):
            return self.trigger.threshold
        if isinstance(self.trigger, AdaptiveTrigger):
            return self.trigger.threshold
        return 0.75

    # ── 触发判断 ──────────────────────────────────────────────────

    def should_compress(
        self,
        conversation: "Conversation",
        model_id: Optional[str] = None,
    ) -> bool:
        """纯判断: 是否应该压缩 (无副作用)."""
        # 条件 1: 消息数太少不值得压缩
        if len(conversation.messages) < self.min_messages:
            return False
        # 条件 2: 用量未达阈值
        usage = self.measure(conversation, model_id)
        if not self.trigger.should_compress(usage):
            return False
        # 条件 3: 冷却中
        if not self._cooldown_elapsed(conversation.conversation_id):
            return False
        return True

    def _cooldown_elapsed(self, conv_id: str) -> bool:
        last = self._last_compress_at.get(conv_id)
        if last is None:
            return True
        return (time.time() - last) >= self.cooldown_seconds

    # ── 主入口 ────────────────────────────────────────────────────

    async def maybe_compress(
        self,
        conversation: "Conversation",
        model_id: Optional[str] = None,
        force: bool = False,
    ) -> Optional[CompressedContext]:
        """检查并可能压缩. None 表示未触发.

        Args:
            conversation: 对话对象 (会被原地修改: 早期消息替换为一条 summary)
            model_id: 当前模型 ID (用于算 context window)
            force: 强制压缩 (跳过所有判断)
        """
        if not force and not self.should_compress(conversation, model_id):
            return None

        return await self._do_compress(conversation, model_id, force=force)

    async def _do_compress(
        self,
        conversation: "Conversation",
        model_id: Optional[str] = None,
        force: bool = False,
    ) -> CompressedContext:
        """执行实际的压缩. 调用方需保证该执行. 会修改 conversation.messages."""
        from jarvis.core.entities import Message

        t0 = time.time()
        before = messages_tokens([
            {"role": m.role, "content": m.content} for m in conversation.messages
        ])

        # 切片: 留尾部 keep_recent 条原文, 前段丢给 summarizer
        msgs_to_summarize = list(conversation.messages[:-self.keep_recent]) \
            if len(conversation.messages) > self.keep_recent \
            else list(conversation.messages)
        kept = list(conversation.messages[-self.keep_recent:])

        if not msgs_to_summarize:
            logger.debug("[Compressor] 没有可压缩的消息, 跳过")
            return None

        logger.info(
            f"[Compressor] 触发 | conv={conversation.conversation_id[:8]}... "
            f"msgs={len(conversation.messages)} summarize={len(msgs_to_summarize)} "
            f"keep={len(kept)} before_tokens={before}"
        )

        # 调 LLM 摘要
        summary = await self.summarizer(
            self.router,
            [{"role": m.role, "content": m.content} for m in msgs_to_summarize],
            model=model_id,
        )
        if not summary:
            logger.warning("[Compressor] 摘要为空, 跳过替换")
            return None

        # 替换 conversation.messages: 一条 summary 消息 + 保留的近期原文
        summary_msg = Message(
            role="system",
            content=f"[早期对话摘要 — 共 {len(msgs_to_summarize)} 条消息]\n{summary}",
        )
        conversation.messages = [summary_msg, *kept]

        # 计算 after
        after = messages_tokens([
            {"role": m.role, "content": m.content} for m in conversation.messages
        ])

        result = CompressedContext(
            conversation_id=conversation.conversation_id,
            summary=summary,
            kept_messages=[m.to_dict() for m in kept],
            dropped_count=len(msgs_to_summarize),
            before_tokens=before,
            after_tokens=after,
            compression_ratio=(before / max(after, 1)),
            elapsed_ms=(time.time() - t0) * 1000,
            trigger_reason="force" if force else "threshold",
        )

        # 更新状态
        self._last_compress_at[conversation.conversation_id] = time.time()
        self._compress_count[conversation.conversation_id] = (
            self._compress_count.get(conversation.conversation_id, 0) + 1
        )
        if isinstance(self.trigger, AdaptiveTrigger):
            self.trigger.update_last_tokens(conversation.conversation_id, after)

        # 持久化 (如果注入了 persist_fn)
        if self.persist_fn is not None:
            try:
                await self.persist_fn(conversation)
                logger.debug(f"[Compressor] 已持久化 | conv={conversation.conversation_id[:8]}...")
            except Exception as e:
                logger.warning(f"[Compressor] 持久化失败: {e}")

        logger.info(
            f"[Compressor] 完成 | dropped={result.dropped_count} "
            f"kept={len(result.kept_messages)} "
            f"{result.before_tokens}→{result.after_tokens} tokens "
            f"ratio={result.compression_ratio:.2f}x "
            f"elapsed={result.elapsed_ms:.0f}ms"
        )
        return result

    # ── 监控 ──────────────────────────────────────────────────────

    def get_stats(self, conv_id: str) -> dict:
        """获取某个对话的压缩统计."""
        return {
            "conversation_id": conv_id,
            "compress_count": self._compress_count.get(conv_id, 0),
            "last_compress_at": self._last_compress_at.get(conv_id),
        }

    def reset_stats(self, conv_id: Optional[str] = None):
        """重置统计. conv_id=None 重置全部."""
        if conv_id is None:
            self._last_compress_at.clear()
            self._compress_count.clear()
        else:
            self._last_compress_at.pop(conv_id, None)
            self._compress_count.pop(conv_id, None)