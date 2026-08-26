# jarvis/core/agent_loop.py
"""公共 Agent Loop — chat / stream_chat / stream_chat_with_messages 三处共用.

设计动机
--------
原 chat_engine 三处入口各自实现 tool loop, 代码重复且非流式 chat() **漏写
assistant turn** —— 下一轮 LLM 看到孤儿 tool_result 报 400 / 2013.

本模块把 "tool loop 迭代 + assistant turn 注入 + tool_result 回填 + 约束 hint"
抽出来, 让三处入口共用同一份逻辑. chat_engine 只负责:
  - Phase 1: 调 LLM (流式/非流式 各异)
  - Phase 2+: async for event in runner.run_iterations(...):
      stream_chat* 把 event 序列化成 SSE 推前端
      chat()       忽略 event, 只取 final result

PR2 覆盖:
  - 修核心 bug: 每轮注入 assistant turn (含 tool_use 块) 在 tool_result 之前
  - 加 iteration hint / stop hint (默认开, 配 AgentLoopConfig 关)
  - 去重 (tool_name, params) 相同则跳过
  - parallel tool exec (asyncio.gather)
  - provider_protocol 分发 tool_result 格式 (anthropic / openai)

PR3 会把 OpenAI / MiniMax adapter 的 provider_protocol 设为 "openai",
adapter 自己负责 tool_calls → content_blocks 转换.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Optional, AsyncIterator, TYPE_CHECKING

from jarvis.core.tool_parser import ToolCall
from jarvis.core.tool_result_formatter import ToolResultFormatter
from jarvis.utils.logger import get_logger

if TYPE_CHECKING:
    from jarvis.services.ai.router import AIRouter

logger = get_logger(__name__)


# ── 配置 ─────────────────────────────────────────────────────────────


@dataclass
class AgentLoopConfig:
    """Agent loop 运行时配置.

    Defaults aligned with PR1 / PR2 review 决策:
      - max_iterations=8 (review 后从 5 提到 8, 由 ChatEngine 从 Settings 注入)
      - provider_protocol="anthropic" (Anthropic / Ollama 默认;
        OpenAI / MiniMax 由 PR3 切到 "openai")
    """
    max_iterations: int = 8
    provider_protocol: str = "anthropic"   # "anthropic" | "openai"
    parallel_tool_exec: bool = True
    dedup_tool_calls: bool = True
    inject_iteration_hint: bool = True
    inject_stop_hint_on_max: bool = True


# ── 迭代结果 ─────────────────────────────────────────────────────────


@dataclass
class ToolExecution:
    """一次工具调用的完整执行记录 (用于持久化 / SSE)."""
    tool_call: ToolCall
    result: Any
    status: str
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "tool": self.tool_call.tool,
            "action": self.tool_call.action,
            "params": self.tool_call.params,
            "status": self.status,
            "error": self.error,
            "result": self.result,
        }


@dataclass
class AgentLoopResult:
    """Agent loop 最终结果."""
    final_text: str
    final_thinking: str = ""
    tool_executions: list[ToolExecution] = field(default_factory=list)
    iterations_used: int = 0
    max_iterations_reached: bool = False

    def to_message_payload(self) -> dict:
        """返回主对话结果 dict (兼容 chat() 现有签名)."""
        return {
            "text": self.final_text,
            "thinking": self.final_thinking,
            "iterations": self.iterations_used,
            "max_iterations_reached": self.max_iterations_reached,
        }


# ── Runner ───────────────────────────────────────────────────────────


class AgentLoopRunner:
    """公共 Agent Loop. 单实例可复用, 内部无状态.

    Usage:
        runner = AgentLoopRunner(config, task_executor, tool_parser)

        # 非流式入口 (chat())
        async for event in runner.run_iterations(
            messages, router, model=..., instance=...,
            current_text=..., current_tool_uses=[...],
        ):
            pass  # chat() 不消费事件

        # 流式入口 (stream_chat*): 把 event 转 SSE 推前端
        async for event in runner.run_iterations(...):
            yield json.dumps(event)
    """

    def __init__(self, config: AgentLoopConfig, task_executor, tool_parser):
        self.config = config
        self.task_executor = task_executor
        self.tool_parser = tool_parser

    # ── Public entry ──────────────────────────────────────────────

    async def run_iterations(
        self,
        messages: list[dict],
        router: "AIRouter",
        *,
        model: Optional[str],
        instance,
        # Phase 1 已完成, 由调用方把响应塞进来
        current_text: str,
        current_thinking: str = "",
        current_content_blocks: Optional[list] = None,
        current_tool_uses: Optional[list] = None,
    ) -> AsyncIterator[dict]:
        """Phase 2+ 迭代.

        Yields:
          {"type": "tool_iter", "iteration": int, "max": int}
          {"type": "tool_call", "tool": ..., "action": ..., "params": ...}
          {"type": "tool_result", "tool": ..., "action": ..., "status": ..., "result": ...}
          {"type": "tool_skipped", "tool": ..., "reason": "duplicate"}
          {"type": "result", "result": AgentLoopResult}   ← 最后一条

        注意: tool_iter 从 2 开始 (Phase 1 是 iteration 1, 已由调用方跑完).
        """
        iteration = 1
        tool_executions: list[ToolExecution] = []
        text = current_text
        thinking = current_thinking
        tool_uses = list(current_tool_uses or [])

        # Phase 1 已有 tool_use → 直接进入 Phase 2
        while tool_uses and iteration < self.config.max_iterations:
            iteration += 1
            yield {
                "type": "tool_iter",
                "iteration": iteration,
                "max": self.config.max_iterations,
            }
            logger.debug(
                f"[AgentLoop] iter {iteration}/{self.config.max_iterations} "
                f"| tool_uses={len(tool_uses)}"
            )

            # 1) 注入 iteration hint (iteration > 2 才提示, 避免第 2 轮就喧宾夺主)
            if self.config.inject_iteration_hint and iteration > 2:
                self._inject_hint(messages, iteration, self.config.max_iterations)

            # 2) 注入 assistant turn (含 tool_use 块) — 修核心 bug
            assistant_turn = self._build_assistant_turn(
                current_content_blocks, current_text
            )
            messages.append(assistant_turn)

            # 3) 去重
            if self.config.dedup_tool_calls:
                unique_uses, skipped_uses = self._dedup(tool_uses)
                for sk in skipped_uses:
                    yield {
                        "type": "tool_skipped",
                        "tool": sk.get("name", ""),
                        "reason": "duplicate",
                    }
            else:
                unique_uses = tool_uses

            # 4) 执行工具 (并行可选)
            for tu in unique_uses:
                yield {
                    "type": "tool_call",
                    "tool": tu.get("name", ""),
                    "action": (tu.get("input", {}) or {}).get("action", ""),
                    "params": tu.get("input", {}) or {},
                }

            exec_results = await self._exec_tools(unique_uses)

            # 5) tool_result 回填 + SSE 推送
            for tu, er in zip(unique_uses, exec_results):
                tool_call = self._to_tool_call(tu)
                self._append_tool_result(messages, tool_call, er)
                tool_executions.append(
                    ToolExecution(
                        tool_call=tool_call,
                        result=er,
                        status=er.get("status", "success") if isinstance(er, dict) else "success",
                        error=er.get("message") if isinstance(er, dict) and er.get("status") == "error" else None,
                    )
                )
                yield {
                    "type": "tool_result",
                    "tool": tool_call.tool,
                    "action": tool_call.action,
                    "status": er.get("status", "success") if isinstance(er, dict) else "success",
                    "result": er,
                }

            # 6) 末轮 stop hint (下一轮 LLM 才会看到)
            if (
                iteration == self.config.max_iterations
                and self.config.inject_stop_hint_on_max
            ):
                self._inject_stop_hint(messages)

            # 7) 下一轮非流式 LLM
            response = await router.chat(
                messages, model=model, instance=instance, stream=False
            )
            text = response.content or ""
            thinking = (
                response.thinking
                if isinstance(getattr(response, "thinking", ""), str)
                else ""
            )
            current_content_blocks = response.content_blocks or []
            tool_uses = self._extract_tool_uses(current_content_blocks, text)

        # ── 终止: tool_uses 为空 或 达到 max_iterations ──
        max_reached = iteration >= self.config.max_iterations and bool(tool_uses)
        if max_reached:
            logger.warning(
                f"[AgentLoop] max_iterations reached ({self.config.max_iterations}) "
                "without final text; returning last response"
            )

        yield {
            "type": "result",
            "result": AgentLoopResult(
                final_text=text,
                final_thinking=thinking,
                tool_executions=tool_executions,
                iterations_used=iteration,
                max_iterations_reached=max_reached,
            ),
        }

    # ── Helpers ───────────────────────────────────────────────────

    @staticmethod
    def _extract_tool_uses(content_blocks: Optional[list], text: str) -> list[dict]:
        """从 LLM 响应中提取 tool_use (Anthropic content_blocks)."""
        out: list[dict] = []
        if content_blocks:
            for b in content_blocks:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    out.append(b)
        return out

    def _to_tool_call(self, tu: dict) -> ToolCall:
        """把 content_block 形态的 tool_use 转 ToolCall (id 必填)."""
        return ToolCall(
            tool=tu.get("name", ""),
            action=(tu.get("input", {}) or {}).get("action", ""),
            params=tu.get("input", {}) or {},
            id=tu.get("id", ""),                # __post_init__ 兜底
            raw_input_json=json.dumps(tu),
        )

    def _build_assistant_turn(
        self, content_blocks: Optional[list], text: str
    ) -> dict:
        """构造 assistant turn — 修复 chat() 漏写的核心 bug.

        返回的 dict 严格遵循 Anthropic /v1/messages 形态:
            {"role": "assistant", "content": [<thinking>, <text>, <tool_use>, ...]}
        即使 text 为空也保留 text block (Anthropic 允许 content=[] 但显式 text 更稳).
        """
        blocks: list[dict] = []
        if content_blocks:
            # 把 thinking/text/tool_use 原样保留 (content_blocks 已经是 Anthropic 形态)
            for b in content_blocks:
                if isinstance(b, dict):
                    blocks.append(b)
        if text and not any(b.get("type") == "text" for b in blocks if isinstance(b, dict)):
            blocks.append({"type": "text", "text": text})
        if not blocks:
            # 兜底: 完全没有内容时给一个空 text block, 避免 Anthropic 协议报错
            blocks.append({"type": "text", "text": ""})
        return {"role": "assistant", "content": blocks}

    def _append_tool_result(
        self, messages: list[dict], tool_call: ToolCall, exec_result: Any
    ) -> None:
        """按 provider_protocol 注入 tool_result.

        Anthropic / Ollama: role=user, content=[{type:tool_result, tool_use_id, content}]
        OpenAI / MiniMax:    role=tool, tool_call_id, content
        """
        content = ToolResultFormatter.format_plain(
            tool=tool_call.tool,
            action=tool_call.action,
            params=tool_call.params,
            result=exec_result,
        )
        if self.config.provider_protocol == "openai":
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": content,
            })
        else:
            # anthropic / 默认
            messages.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": tool_call.id,
                    "content": content,
                }],
            })

    @staticmethod
    def _inject_hint(messages: list[dict], iteration: int, max_iter: int) -> None:
        """每轮开头注入'迭代计数'提示, 让 LLM 自觉控制节奏."""
        messages.append({
            "role": "user",
            "content": (
                f"[系统提示] 当前工具迭代第 {iteration}/{max_iter} 轮。"
                "如已获得足够信息, 请直接回答用户, 不再调用工具。"
            ),
        })

    @staticmethod
    def _inject_stop_hint(messages: list[dict]) -> None:
        """最后一轮强制提示停止 — 即使 LLM 还想继续."""
        messages.append({
            "role": "user",
            "content": (
                "[系统提示] 已达最大工具迭代次数。请基于已有工具结果直接"
                "给出最终回答, 不再调用任何工具。"
            ),
        })

    @staticmethod
    def _dedup(tool_uses: list[dict]) -> tuple[list[dict], list[dict]]:
        """去掉 (tool, input) 完全相同的重复调用. 同 (tool,params) 只执行第一次."""
        seen: set[str] = set()
        unique: list[dict] = []
        skipped: list[dict] = []
        for tu in tool_uses:
            key = (
                tu.get("name", ""),
                json.dumps(tu.get("input", {}) or {}, sort_keys=True, ensure_ascii=False),
            )
            seed = f"{key[0]}|{key[1]}"
            h = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]
            if h in seen:
                skipped.append(tu)
                continue
            seen.add(h)
            unique.append(tu)
        return unique, skipped

    async def _exec_tools(self, tool_uses: list[dict]) -> list[Any]:
        """执行工具调用. 多于 1 个时并行 (默认开)."""
        if not tool_uses:
            return []
        if self.config.parallel_tool_exec and len(tool_uses) > 1:
            logger.debug(f"[AgentLoop] parallel exec {len(tool_uses)} tools")
            return await asyncio.gather(
                *[self._exec_one(tu) for tu in tool_uses],
                return_exceptions=False,
            )
        return [await self._exec_one(tu) for tu in tool_uses]

    async def _exec_one(self, tu: dict) -> Any:
        """执行单个工具调用, 异常也包成 status=error 返回."""
        from jarvis.core.entities import Step
        tool_name = tu.get("name", "")
        params = tu.get("input", {}) or {}
        try:
            step = Step(tool=tool_name, params=params)
            return await self.task_executor.execute_step(step)
        except Exception as e:
            logger.error(f"[AgentLoop] tool {tool_name} failed: {e}")
            return {"status": "error", "message": str(e)}
