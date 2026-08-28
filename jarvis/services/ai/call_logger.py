# jarvis/services/ai/call_logger.py
"""LLM 模型调用日志 — 记录每一次 chat/chat_stream 的 body 和 response.

设计目标
--------
- 完整捕获每次 LLM 调用的入参 (messages + tools) 和出参 (content_blocks / thinking / usage)
- 按日期分目录 `workspace/logs/llm_calls/YYYY-MM-DD/`
- 每条调用 = 1 个 JSON 详情文件 + 1 行 index 记录 (便于快速列表)
- 异步写入用 asyncio.to_thread 避免阻塞 chat 主流程
- 通过全局单例 `get_call_logger()` 接入, 不影响业务代码

存储模型
--------
logs/llm_calls/
└── 2026-08-28/
    ├── index.jsonl                       # 一行一个调用摘要 (供列表 API 快速读)
    └── <call_id>.json                    # 单次调用完整记录 (含 request/response body)

Call ID 格式: `cl-<timestamp_ms>-<sha1[:6]>` — 全局唯一, 时间序可读.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Union

from jarvis.config import settings
from jarvis.utils.logger import get_logger

logger = get_logger(__name__)

# ── 公开 API ───────────────────────────────────────────────────────
# adapter 拿到 call_id 后, 直接调 enrich_raw_body 写 raw HTTP body.
# call_id 由 router 显式传入 (作为参数), 不再用 ContextVar — 后者在
# async generator finally 里 reset 会抛 "was created in a different Context".


def enrich_raw_body(
    call_id: Optional[str],
    *,
    raw_request: Optional[dict] = None,
    raw_response: Optional[Any] = None,
    raw_stream_events: Optional[list] = None,
) -> None:
    """adapter 调用 — 给已开始的 call 写入原始 HTTP body (供 raw 追溯).

    Args:
      call_id:        start_call 返回的 call_id (None 时静默忽略)
      raw_request:    实际发给 provider 的 HTTP payload
      raw_response:   完整 HTTP response body (非流场景)
      raw_stream_events: 流式场景下所有 SSE 事件列表
    """
    if not call_id:
        return
    rec = LLMCallLogger.instance()._records.get(call_id)
    if rec is None:
        return
    if raw_request is not None:
        rec.request.setdefault("raw_http_body", raw_request)
    if raw_response is not None:
        rec.response["raw_http_body"] = raw_response
    if raw_stream_events is not None:
        rec.response["raw_stream_events"] = raw_stream_events


# ── 数据结构 ─────────────────────────────────────────────────────────


@dataclass
class LLMCallRecord:
    """单次 LLM 调用的完整记录 — 持久化到 JSON 详情文件.

    Fields:
      call_id:            全局唯一 ID (cl-<ms>-<hash6>)
      timestamp:          起始时间 ISO 8601 (UTC + 本地偏移)
      timestamp_ms:       起始时间戳毫秒
      model:              模型名 (e.g. "qwen3:4b", "claude-3-5-sonnet")
      provider:           provider 标识 (e.g. "ollama", "openai", "anthropic")
      provider_protocol:  "anthropic" | "openai" | None
      conversation_id:    调用方传入的会话 ID (便于追溯到具体对话)
      request: {
        messages:         完整 messages 列表 (role + content + tool_calls / tool_use_id 等)
        tools:            工具 schema 列表 (供调试 LLM 看到什么工具)
        stream:           是否流式
        max_tokens:       max_tokens 参数
        temperature:      temperature 参数
        extra:            其他透传字段 (raw HTTP payload 也可放这)
      }
      response: {
        content:          最终文本
        thinking:         reasoning 文本 (如有)
        content_blocks:   完整 content_blocks (含 tool_use / tool_calls)
        usage:            token usage
        raw:              provider 返回的原始 JSON (Anthropic/Ollama 完整 data dict;
                          OpenAI 的完整 choices/usage)
        stop_reason:      finish_reason (OpenAI) / message_delta.stop_reason (Anthropic)
      }
      latency_ms:         从请求发起 → 收到完整响应的总耗时
      status:             "success" | "error" | "stream_interrupted"
      error:              异常 message (status="error" 时填充)
      source:             调用入口标识 — "router.chat" | "router.chat_stream_full"
                          | "agent_loop.iter" | "vision_analyze" | 其他
      metadata:           调用方附加字段 (e.g. {"iteration": 2, "tool_use_count": 1})
    """
    call_id: str
    timestamp: str
    timestamp_ms: int
    model: str
    provider: str
    provider_protocol: Optional[str]
    conversation_id: Optional[str]
    request: dict = field(default_factory=dict)
    response: dict = field(default_factory=dict)
    latency_ms: float = 0.0
    status: str = "success"
    error: Optional[str] = None
    source: str = ""
    metadata: dict = field(default_factory=dict)

    def to_index_entry(self) -> dict:
        """生成 index.jsonl 的摘要行 — 体积小, 列表查询不读详情文件."""
        return {
            "call_id": self.call_id,
            "timestamp": self.timestamp,
            "timestamp_ms": self.timestamp_ms,
            "model": self.model,
            "provider": self.provider,
            "provider_protocol": self.provider_protocol,
            "conversation_id": self.conversation_id,
            "source": self.source,
            "latency_ms": round(self.latency_ms, 1),
            "status": self.status,
            "messages_count": len(self.request.get("messages") or []),
            "has_tool_use": bool(
                self.response.get("content_blocks")
                and any(
                    (b.get("type") == "tool_use") if isinstance(b, dict) else False
                    for b in self.response["content_blocks"]
                )
            ),
            "thinking_chars": len(self.response.get("thinking") or ""),
            "response_chars": len(self.response.get("content") or ""),
            "error": self.error,
        }

    def to_full_dict(self) -> dict:
        return asdict(self)


# ── Logger ───────────────────────────────────────────────────────────


class LLMCallLogger:
    """LLM 调用日志器 (单例).

    Usage:
        from jarvis.services.ai.call_logger import get_call_logger

        cl = get_call_logger()

        # 方式 1: 全自动 (上下文管理器)
        async with cl.trace(model="qwen3:4b", provider="ollama",
                             conversation_id=conv_id, source="router.chat") as rec:
            response = await client.chat(messages)
            rec.set_response(content=response.content,
                             content_blocks=response.content_blocks,
                             thinking=response.thinking,
                             usage=response.usage.to_dict() if response.usage else None,
                             raw=response.raw)
        # 退出 with 时自动 flush

        # 方式 2: 手动
        rec = cl.start_call(model=..., provider=..., source=...)
        try:
            ...
            cl.end_call(rec, response=..., status="success")
        except Exception as e:
            cl.end_call(rec, status="error", error=str(e))
    """

    _instance: Optional["LLMCallLogger"] = None
    _lock = threading.Lock()

    def __init__(self):
        # 日志根目录: workspace/logs/llm_calls/
        # 兼容 settings.storage.logs_dir (项目根 logs/)
        base = settings.storage.logs_dir
        self.base_dir = base / "llm_calls"
        self.base_dir.mkdir(parents=True, exist_ok=True)

        # 写入并发控制 — JSONL append, 跨线程安全
        self._write_lock = threading.Lock()

        # 进行中的 call records (供 adapter 通过 contextvar 反查 + enrich)
        self._records: dict[str, LLMCallRecord] = {}
        self._record_lock = threading.Lock()

        # ★ 进行中的 flush task 引用 — 防止 async generator aclose() 时被 GC 掉.
        # asyncio.create_task 创建的 task 如果不持有引用, 在 generator 被关闭
        # 那一瞬间就会被垃圾回收, 导致 _flush() 永远不执行.
        self._pending_tasks: set[asyncio.Task] = set()

    # ── Singleton ─────────────────────────────────────────────────

    @classmethod
    def instance(cls) -> "LLMCallLogger":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ── 公共 API ───────────────────────────────────────────────────

    def start_call(
        self,
        *,
        model: str,
        provider: str,
        provider_protocol: Optional[str] = None,
        conversation_id: Optional[str] = None,
        source: str = "",
        request: Optional[dict] = None,
        metadata: Optional[dict] = None,
    ) -> LLMCallRecord:
        """开始记录一次调用 — 返回 record, 调用方负责填充 response + 调 end_call."""
        now_ms = int(time.time() * 1000)
        seed = f"{now_ms}-{uuid.uuid4().hex[:6]}"
        call_id = "cl-" + hashlib.sha1(seed.encode()).hexdigest()[:10]
        rec = LLMCallRecord(
            call_id=call_id,
            timestamp=datetime.fromtimestamp(now_ms / 1000).isoformat(timespec="milliseconds"),
            timestamp_ms=now_ms,
            model=model or "",
            provider=provider or "",
            provider_protocol=provider_protocol,
            conversation_id=conversation_id,
            request=request or {},
            source=source,
            metadata=metadata or {},
        )
        # 注册到 in-memory 字典 (供 adapter enrich)
        with self._record_lock:
            self._records[call_id] = rec
        return rec

    def end_call(
        self,
        record: LLMCallRecord,
        *,
        response: Optional[dict] = None,
        status: str = "success",
        error: Optional[str] = None,
    ) -> None:
        """结束记录 — 同步 flush 到磁盘."""
        logger.warning(f"[DEBUG-CL] end_call ENTER for {record.call_id}")
        record.latency_ms = (time.time() * 1000) - record.timestamp_ms
        record.status = status
        record.error = error
        if response:
            for k, v in response.items():
                record.response[k] = v
        with self._record_lock:
            self._records.pop(record.call_id, None)

        try:
            self._write_sync(record)
            logger.warning(f"[DEBUG-CL] _write_sync OK for {record.call_id}")
        except Exception as e:
            logger.error(f"[CallLogger] sync write failed for {record.call_id}: {type(e).__name__}: {e}")

    def trace(self, **kwargs) -> "_TraceContext":
        """上下文管理器 — 自动 start_call / end_call."""
        return _TraceContext(self, **kwargs)

    # ── 持久化 ─────────────────────────────────────────────────────

    async def _flush(self, record: LLMCallRecord) -> None:
        """异步写入: index.jsonl (append) + <call_id>.json (详情)."""
        logger.warning(f"[DEBUG-CL] _flush start for {record.call_id}")
        try:
            await asyncio.to_thread(self._write_sync, record)
            logger.warning(f"[DEBUG-CL] _flush done for {record.call_id}")
        except Exception as e:
            logger.error(f"[CallLogger] flush failed for {record.call_id}: {e}")

    def _write_sync(self, record: LLMCallRecord) -> None:
        """同步写入 (在线程池里跑)."""
        day_dir = self.base_dir / datetime.fromtimestamp(record.timestamp_ms / 1000).strftime("%Y-%m-%d")
        day_dir.mkdir(parents=True, exist_ok=True)

        detail_path = day_dir / f"{record.call_id}.json"
        index_path = day_dir / "index.jsonl"

        with self._write_lock:
            # 详情文件 — 完整 JSON
            detail_path.write_text(
                json.dumps(record.to_full_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            # index — 追加一行 (JSONL)
            with index_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record.to_index_entry(), ensure_ascii=False) + "\n")

    # ── 查询 (供 API 用) ──────────────────────────────────────────

    def list_calls(
        self,
        *,
        date: Optional[str] = None,           # "YYYY-MM-DD" 或 None (今天)
        limit: int = 100,
        offset: int = 0,
        conversation_id: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        status: Optional[str] = None,
    ) -> dict:
        """读取 index.jsonl, 返回分页摘要列表.

        Returns:
          {"total": int, "items": [...], "date": "YYYY-MM-DD"}
        """
        date_str = date or datetime.now().strftime("%Y-%m-%d")
        index_path = self.base_dir / date_str / "index.jsonl"

        items: list[dict] = []
        total = 0
        if index_path.exists():
            # 倒序读 (最新的在前) — 但 JSONL append-only, 只能顺序读, 反转后切片
            # 当 limit 较大时, 全读后再切; 后续可改成"按日期 + 滚动指针"优化
            try:
                lines = index_path.read_text(encoding="utf-8").splitlines()
            except Exception as e:
                logger.warning(f"[CallLogger] read index failed: {e}")
                lines = []
            # 倒序
            lines.reverse()
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # 过滤
                if conversation_id and entry.get("conversation_id") != conversation_id:
                    continue
                if provider and entry.get("provider") != provider:
                    continue
                if model and entry.get("model") != model:
                    continue
                if status and entry.get("status") != status:
                    continue
                total += 1
                if offset <= total - 1 < offset + limit:
                    items.append(entry)

        return {
            "date": date_str,
            "total": total,
            "offset": offset,
            "limit": limit,
            "items": items,
        }

    def get_call(self, call_id: str) -> Optional[dict]:
        """读取单条调用的完整详情."""
        if not call_id or "/" in call_id or ".." in call_id:
            return None  # 防路径穿越
        # call_id 形如 "cl-xxxxxxxxxx" — 扫描所有日期目录
        # 实际一般查最近几天的 index, 这里全量扫 (文件数有限, 几百量级)
        for day_dir in sorted(self.base_dir.iterdir(), reverse=True):
            if not day_dir.is_dir():
                continue
            detail = day_dir / f"{call_id}.json"
            if detail.exists():
                try:
                    return json.loads(detail.read_text(encoding="utf-8"))
                except Exception as e:
                    logger.error(f"[CallLogger] read detail failed: {e}")
                    return None
        return None

    def list_dates(self) -> list[str]:
        """列出所有有日志的日期 (最近的在前)."""
        if not self.base_dir.exists():
            return []
        return sorted(
            [d.name for d in self.base_dir.iterdir() if d.is_dir()],
            reverse=True,
        )

    def clear(self, date: Optional[str] = None) -> dict:
        """清空日志. date=None 清全部; 否则只清指定日期."""
        if date:
            target = self.base_dir / date
            if not target.exists():
                return {"removed": 0, "path": str(target)}
            count = sum(1 for _ in target.glob("*.json"))
            import shutil
            shutil.rmtree(target)
            return {"removed": count, "path": str(target)}

        # 全清
        total = 0
        for d in self.base_dir.iterdir():
            if d.is_dir():
                total += sum(1 for _ in d.glob("*.json"))
                import shutil
                shutil.rmtree(d)
        return {"removed": total, "path": str(self.base_dir)}


# ── 上下文管理器 ──────────────────────────────────────────────────────


class _TraceContext:
    """`async with cl.trace(...) as rec:` 自动管理 start/end."""

    def __init__(self, logger: LLMCallLogger, **kwargs):
        self._logger = logger
        self._kwargs = kwargs
        self.record: Optional[LLMCallRecord] = None

    async def __aenter__(self) -> LLMCallRecord:
        self.record = self._logger.start_call(**self._kwargs)
        return self.record

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self.record is None:
            return
        if exc_type is not None:
            self._logger.end_call(
                self.record,
                status="error",
                error=f"{exc_type.__name__}: {exc}",
            )
        # success 路径由调用方显式 end_call, 或在 __aenter__ 返回前就调用了
        # 这里不再 end_call, 避免覆盖调用方填充的 response
        return None

    # ── record 上的便捷方法 ──────────────────────────────────────

    def set_response(
        self,
        *,
        content: Optional[str] = None,
        thinking: Optional[str] = None,
        content_blocks: Optional[list] = None,
        usage: Optional[dict] = None,
        raw: Optional[dict] = None,
        stop_reason: Optional[str] = None,
    ) -> None:
        if self.record is None:
            return
        self.record.response = {
            "content": content or "",
            "thinking": thinking or "",
            "content_blocks": content_blocks or [],
            "usage": usage or {},
            "raw": raw,
            "stop_reason": stop_reason or "",
        }

    def set_request(
        self,
        *,
        messages: Optional[list] = None,
        tools: Optional[list] = None,
        stream: Optional[bool] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        extra: Optional[dict] = None,
    ) -> None:
        if self.record is None:
            return
        req = self.record.request or {}
        if messages is not None:
            req["messages"] = messages
        if tools is not None:
            req["tools"] = tools
        if stream is not None:
            req["stream"] = stream
        if max_tokens is not None:
            req["max_tokens"] = max_tokens
        if temperature is not None:
            req["temperature"] = temperature
        if extra:
            req["extra"] = extra
        self.record.request = req

    def end(self, *, status: str = "success", error: Optional[str] = None) -> None:
        if self.record is None:
            return
        self._logger.end_call(self.record, status=status, error=error)


# ── 单例 ──────────────────────────────────────────────────────────────


def get_call_logger() -> LLMCallLogger:
    """便捷获取单例."""
    return LLMCallLogger.instance()
