# jarvis/core/tool_history.py
"""工具执行历史压缩 — 把 tool/tool_result 消息转成自然语言摘要.

设计动机
--------
Anthropic /v1/messages 严格只接受 system/user/assistant 三种 role.
原 ContextManager._sanitize_history 直接丢弃 tool/tool_result, 但
这些消息记录了 LLM 调用过的工具和结果, 是有价值的上下文. 丢掉的代价:

  - 多轮对话中 LLM 不知道"我之前已经读过这个文件了" — 重复调工具
  - LLM 看不到之前工具的输出 — 无法基于历史结果继续推理
  - 单个 tool_result 可能很大 (读大文件 / bash 输出), 但只能整体裁剪

本模块把 tool/tool_result 转成 user role 的自然语言摘要:

    [工具执行 #1] bash.exec
      参数: {"cmd": "ls -la"}
      结果: <truncated to max_single_result_chars>
    [工具执行 #2] file.read
      参数: {"path": "/tmp/big.txt"}
      结果: <truncated>

当所有工具摘要的累计 token > aggregate_token_threshold 时, 把早期 turn
合并为一段 [早期工具执行摘要], 保留最近 K 个 turn 的原文 (详细).

与 ContextManager 的关系:
  - build_messages() 在 _sanitize_history 之前调用本模块
  - 转换后 history 仍含 tool/tool_result 之外的 role, 走原本的 strict
    sanitize 是 no-op (无新丢弃)
  - 工具摘要 role=user, prefix="[工具执行]" 或 "[早期工具执行摘要]",
    LLM 训练时见过类似 system-info-as-user 模式 (与 _inject_hint 同风格)
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from jarvis.utils.logger import get_logger

logger = get_logger(__name__)


def _count_tokens(text: str) -> int:
    """轻量级 token 估算 — 不依赖 context_manager, 避免循环导入.

    与 context_manager.count_tokens 一致: 优先 tiktoken, 否则 4 字符/token.
    此处保留独立实现, 因为本模块被 context_manager 导入, 不能反向依赖.
    """
    if not text:
        return 0
    try:
        import tiktoken
        return len(tiktoken.get_encoding("cl100k_base").encode(text))
    except Exception:
        return max(1, len(text) // 4)


@dataclass
class ToolHistoryStats:
    """工具历史压缩统计 (写进 ContextManager.build_messages 返回的 stats)."""
    tool_turns: int = 0           # 转换出的工具 turn 数
    aggregated: bool = False       # 是否触发了早期聚合
    aggregated_count: int = 0      # 被聚合的早期 turn 数
    total_before_tokens: int = 0   # 聚合前总 token
    total_after_tokens: int = 0    # 聚合后总 token
    kept_recent: int = 0           # 保留的最近 turn 数

    def to_dict(self) -> dict:
        return {
            "tool_turns": self.tool_turns,
            "aggregated": self.aggregated,
            "aggregated_count": self.aggregated_count,
            "total_before_tokens": self.total_before_tokens,
            "total_after_tokens": self.total_after_tokens,
            "kept_recent": self.kept_recent,
        }


class ToolHistoryCompactor:
    """把 tool/tool_result 消息转成自然语言摘要, 超阈值时聚合早期 turn.

    用法:
        compactor = ToolHistoryCompactor()  # 默认参数
        history, stats = compactor.compact(raw_history)

        # 或自定义:
        compactor = ToolHistoryCompactor(
            aggregate_token_threshold=2000,
            keep_recent_turns=6,
            max_single_result_chars=800,
        )

    默认参数:
        aggregate_token_threshold=1500  # 工具历史累计超这个 token 触发聚合
        keep_recent_turns=4             # 无论如何保留最近 N 个工具 turn 原文
        max_single_result_chars=500     # 单个 tool_result 输出截断到 N 字符

    这些数字针对 8K context window 的小模型; 大模型可放大.
    """

    DEFAULT_AGGREGATE_TOKEN_THRESHOLD = 1500
    DEFAULT_KEEP_RECENT_TURNS = 4
    DEFAULT_MAX_SINGLE_RESULT_CHARS = 500

    # 摘要消息的角色 — 用 user 是为了跟 _inject_hint / _inject_stop_hint
    # 的"系统信息伪装成 user"约定一致; LLM 训练时见过这种模式.
    SUMMARY_ROLE = "user"
    SUMMARY_MARKER = "_is_tool_summary"
    SINGLE_PREFIX = "[工具执行]"
    AGGREGATE_PREFIX = "[早期工具执行摘要]"

    def __init__(
        self,
        aggregate_token_threshold: int = DEFAULT_AGGREGATE_TOKEN_THRESHOLD,
        keep_recent_turns: int = DEFAULT_KEEP_RECENT_TURNS,
        max_single_result_chars: int = DEFAULT_MAX_SINGLE_RESULT_CHARS,
        enabled: bool = True,
    ):
        if aggregate_token_threshold < 0:
            raise ValueError("aggregate_token_threshold 必须 >= 0")
        if keep_recent_turns < 0:
            raise ValueError("keep_recent_turns 必须 >= 0")
        if max_single_result_chars < 10:
            raise ValueError("max_single_result_chars 必须 >= 10")
        self.aggregate_token_threshold = aggregate_token_threshold
        self.keep_recent_turns = keep_recent_turns
        self.max_single_result_chars = max_single_result_chars
        self.enabled = enabled

    # ── 主入口 ─────────────────────────────────────────────────────

    def compact(
        self, history: list[dict]
    ) -> tuple[list[dict], ToolHistoryStats]:
        """转换 tool/tool_result → user-role 自然语言摘要.

        Args:
            history: 原始消息列表, 可能含 tool/tool_result

        Returns:
            (transformed_history, stats)
            - transformed_history: tool/tool_result 已被替换为摘要消息
            - stats: ToolHistoryStats
        """
        stats = ToolHistoryStats()

        if not history or not self.enabled:
            return list(history or []), stats

        # Step 1: 转换每个 tool turn → 单个 user-role 摘要
        transformed, tool_turn_indices = self._transform(history)
        stats.tool_turns = len(tool_turn_indices)

        if not tool_turn_indices:
            return transformed, stats

        # Step 2: 计算总 token, 超阈值则聚合早期 turn
        total_before = sum(
            _count_tokens(transformed[i]["content"]) for i in tool_turn_indices
        )
        stats.total_before_tokens = total_before

        if (
            total_before > self.aggregate_token_threshold
            and len(tool_turn_indices) > self.keep_recent_turns
        ):
            transformed, agg_count = self._aggregate_older(
                transformed, tool_turn_indices
            )
            stats.aggregated = True
            stats.aggregated_count = agg_count
            stats.kept_recent = self.keep_recent_turns
            # Recompute after
            new_indices = [
                i for i, m in enumerate(transformed)
                if m.get(self.SUMMARY_MARKER)
            ]
            stats.total_after_tokens = sum(
                _count_tokens(transformed[i]["content"]) for i in new_indices
            )
            logger.info(
                f"[ToolHistory] aggregated | turns={stats.tool_turns} "
                f"older={agg_count} kept_recent={self.keep_recent_turns} "
                f"{total_before}→{stats.total_after_tokens} tokens"
            )
        else:
            stats.total_after_tokens = total_before

        return transformed, stats

    # ── Step 1: 转换 ───────────────────────────────────────────────

    def _transform(
        self, history: list[dict]
    ) -> tuple[list[dict], list[int]]:
        """把 tool/tool_result 替换为自然语言摘要, 记录摘要在 new_history 的 index."""
        new_history: list[dict] = []
        tool_turn_indices: list[int] = []
        pending: list[dict] = []  # 累积 tool call / result, 直到遇到非 tool 消息
        turn_counter = 0

        def flush_pending() -> None:
            nonlocal turn_counter
            if not pending:
                return
            for entry in pending:
                summary = self._summarize_one(
                    tool_name=entry["tool"],
                    action=entry["action"],
                    params=entry["params"],
                    result_msg=entry.get("result_msg"),
                    skipped=entry.get("skipped", False),
                    skip_reason=entry.get("skip_reason", ""),
                    turn_index=turn_counter,
                )
                new_history.append({
                    "role": self.SUMMARY_ROLE,
                    "content": summary,
                    self.SUMMARY_MARKER: True,
                })
                tool_turn_indices.append(len(new_history) - 1)
                turn_counter += 1
            pending.clear()

        for msg in history:
            role = msg.get("role")
            if role == "tool":
                parsed = self._parse_tool_call(msg)
                pending.append(parsed)
            elif role == "tool_result":
                # 尝试配对到最后一个未配对的 tool call
                # 注意: skipped 的 call 也允许配对 — 即便被 dedup 跳过,
                # 如果有结果消息挂上来 (异常流) 也合并为单 turn,
                # 避免产生 (skipped) + (orphan result) 两个 turn.
                paired = False
                for entry in reversed(pending):
                    if entry.get("result_msg") is None:
                        entry["result_msg"] = msg
                        paired = True
                        break
                if not paired:
                    # 孤立的 tool_result (没有对应 tool call)
                    pending.append({
                        "tool": "(orphan)",
                        "action": "",
                        "params": {},
                        "result_msg": msg,
                    })
            else:
                # 非 tool 消息: 先 flush 已累积的 tool turns (插在前面),
                # 然后追加这条消息
                flush_pending()
                new_history.append(msg)

        # 历史末尾: flush 剩余
        flush_pending()

        return new_history, tool_turn_indices

    @staticmethod
    def _parse_tool_call(msg: dict) -> dict:
        """从 tool call 消息中提取结构化字段 (JSON content → dict).

        容忍 JSON 解析失败: 返回 unknown 占位, 不抛异常.
        """
        content = msg.get("content", "")
        data: dict = {}
        if isinstance(content, str):
            try:
                parsed = json.loads(content)
                if isinstance(parsed, dict):
                    data = parsed
            except (json.JSONDecodeError, TypeError):
                data = {}
        elif isinstance(content, dict):
            data = content
        return {
            "tool": str(data.get("tool", "unknown") or "unknown"),
            "action": str(data.get("action", "") or ""),
            "params": data.get("params") or {},
            "skipped": bool(data.get("skipped", False)),
            "skip_reason": str(data.get("reason", "") or ""),
        }

    def _summarize_one(
        self,
        *,
        tool_name: str,
        action: str,
        params: dict,
        result_msg: Optional[dict],
        skipped: bool,
        skip_reason: str,
        turn_index: int,
    ) -> str:
        """生成单个工具 turn 的自然语言摘要."""
        header = f"{self.SINGLE_PREFIX} #{turn_index + 1} — {tool_name}"
        if action:
            header += f".{action}"
        parts = [header]

        if skipped:
            reason = skip_reason or "dedup"
            parts.append(f"  状态: 已跳过 ({reason})")
            return "\n".join(parts)

        # 参数 (截断到合理长度, 避免参数本身就撑爆)
        try:
            params_str = json.dumps(params, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            params_str = str(params)
        if len(params_str) > 200:
            params_str = params_str[:200] + "..."
        parts.append(f"  参数: {params_str}")

        # 结果
        if result_msg is not None:
            result_content = result_msg.get("content", "")
            if isinstance(result_content, list):
                # Anthropic tool_result content blocks — 拼成文本
                chunks = []
                for blk in result_content:
                    if isinstance(blk, dict):
                        t = blk.get("text") or blk.get("content") or ""
                        if t:
                            chunks.append(t)
                result_content = "\n".join(chunks) if chunks else ""
            if not isinstance(result_content, str):
                result_content = str(result_content)
            if not result_content:
                parts.append("  结果: (空)")
            elif len(result_content) > self.max_single_result_chars:
                truncated = result_content[:self.max_single_result_chars]
                parts.append(f"  结果 (截断到 {self.max_single_result_chars} 字符): {truncated}...")
            else:
                parts.append(f"  结果: {result_content}")
        else:
            parts.append("  结果: (无对应结果)")

        return "\n".join(parts)

    # ── Step 2: 聚合 ───────────────────────────────────────────────

    def _aggregate_older(
        self,
        history: list[dict],
        tool_turn_indices: list[int],
    ) -> tuple[list[dict], int]:
        """把除最近 K 个之外的工具 turn 聚合为一条 [早期工具执行摘要] 消息.

        聚合策略: 按 tool.action 分组 + 计数 + 展示状态分布.
        而不是简单地把每条摘要一行行拼起来 (那样 token 数只会更多).

        格式:
            [早期工具执行摘要 — 共 N 次工具调用]
            工具调用统计:
              · bash.exec (×5, 4 成功 / 1 错误)
              · file.read (×2, 2 成功)

        Args:
            history: 已经过 _transform 的消息列表
            tool_turn_indices: 工具摘要消息在 history 中的 index 列表

        Returns:
            (new_history, aggregated_count)
        """
        from collections import Counter, defaultdict

        # 保留最近 K 个 turn 的原文, 聚合更早的 turn
        older_indices = tool_turn_indices[:-self.keep_recent_turns]
        aggregated_count = len(older_indices)

        if aggregated_count == 0:
            return history, 0

        # 解析每个 older turn: 提取 (tool.action) + status
        tool_counter: Counter = Counter()
        status_counter: dict[str, Counter] = defaultdict(Counter)
        for idx in older_indices:
            summary = history[idx]["content"]
            first_line = summary.split("\n", 1)[0] if summary else ""
            # 提取 "[工具执行] #N — bash.exec" → "bash.exec"
            if "— " in first_line:
                tool_action = first_line.split("— ", 1)[1].strip()
            else:
                tool_action = "(unknown)"
            tool_counter[tool_action] += 1
            # 提取状态 (成功 / 错误 / 已跳过)
            if "已跳过" in summary:
                status_counter[tool_action]["skipped"] += 1
            elif "结果 (截断" in summary or "结果:" in summary:
                status_counter[tool_action]["success"] += 1
            else:
                status_counter[tool_action]["unknown"] += 1

        # 构造摘要文本
        lines = [
            f"{self.AGGREGATE_PREFIX} — 共 {aggregated_count} 次工具调用",
            "工具调用统计:",
        ]
        for tool_action, count in tool_counter.most_common():
            sc = status_counter[tool_action]
            breakdown_parts = []
            for status_name in ("success", "skipped", "unknown"):
                n = sc.get(status_name, 0)
                if n:
                    label = {
                        "success": "成功",
                        "skipped": "跳过",
                        "unknown": "未知",
                    }[status_name]
                    breakdown_parts.append(f"{n} {label}")
            breakdown = (
                f", {', '.join(breakdown_parts)}"
                if breakdown_parts else ""
            )
            lines.append(f"  · {tool_action} (×{count}{breakdown})")

        summary_msg = {
            "role": self.SUMMARY_ROLE,
            "content": "\n".join(lines),
            self.SUMMARY_MARKER: True,
        }

        # 替换策略: 用 summary_msg 替换 oldest, 删除中间所有 older,
        # 保留 recent_indices 原样
        first_older_idx = older_indices[0]
        skip_indices = set(older_indices[1:])
        new_history: list[dict] = []
        for i, msg in enumerate(history):
            if i in skip_indices:
                continue
            if i == first_older_idx:
                new_history.append(summary_msg)
            else:
                new_history.append(msg)

        return new_history, aggregated_count
