# jarvis/api/logs.py
"""LLM 调用日志 API — 列表 / 详情 / 清理."""
from fastapi import APIRouter, HTTPException, Query
from typing import Optional

from jarvis.services.ai.call_logger import get_call_logger
from jarvis.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/logs", tags=["logs"])


@router.get("/llm_calls/dates")
async def list_dates():
    """列出所有有日志的日期 (最近的在前)."""
    cl = get_call_logger()
    dates = cl.list_dates()
    return {"dates": dates}


@router.get("/llm_calls")
async def list_calls(
    date: Optional[str] = Query(None, description="YYYY-MM-DD, 默认今天"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    conversation_id: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    status: Optional[str] = None,
):
    """列出某天的所有调用 (分页 + 过滤).

    返回的是 index 摘要行 — 不含完整 request/response body.
    点开某条调用再 GET /llm_calls/{call_id} 拿详情.
    """
    cl = get_call_logger()
    result = cl.list_calls(
        date=date,
        limit=limit,
        offset=offset,
        conversation_id=conversation_id,
        provider=provider,
        model=model,
        status=status,
    )
    return result


@router.get("/llm_calls/{call_id}")
async def get_call(call_id: str):
    """获取单次调用的完整详情 (含 request / response 完整 body)."""
    cl = get_call_logger()
    detail = cl.get_call(call_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"call_id not found: {call_id}")
    return detail


@router.delete("/llm_calls")
async def clear_calls(date: Optional[str] = None):
    """清空日志. date=None 清全部; 否则只清指定日期."""
    cl = get_call_logger()
    result = cl.clear(date=date)
    logger.info(f"[LogsAPI] cleared: {result}")
    return result


@router.get("/llm_calls_stats/summary")
async def summary(date: Optional[str] = None):
    """某天的统计摘要 — 调用次数 / 错误率 / 平均 latency / 按 provider 拆分."""
    cl = get_call_logger()
    listing = cl.list_calls(date=date, limit=10000, offset=0)
    items = listing["items"]

    total = len(items)
    by_status: dict[str, int] = {}
    by_provider: dict[str, int] = {}
    by_model: dict[str, int] = {}
    latencies: list[float] = []

    for it in items:
        s = it.get("status", "unknown")
        by_status[s] = by_status.get(s, 0) + 1
        p = it.get("provider", "unknown")
        by_provider[p] = by_provider.get(p, 0) + 1
        m = it.get("model", "unknown")
        by_model[m] = by_model.get(m, 0) + 1
        lat = it.get("latency_ms", 0)
        if lat and lat > 0:
            latencies.append(lat)

    avg_latency = sum(latencies) / len(latencies) if latencies else 0
    p50 = sorted(latencies)[len(latencies) // 2] if latencies else 0
    p95 = sorted(latencies)[int(len(latencies) * 0.95)] if latencies else 0
    error_count = by_status.get("error", 0)

    return {
        "date": listing["date"],
        "total": total,
        "by_status": by_status,
        "by_provider": by_provider,
        "by_model": by_model,
        "latency_ms": {
            "avg": round(avg_latency, 1),
            "p50": round(p50, 1),
            "p95": round(p95, 1),
            "count": len(latencies),
        },
        "error_rate": round(error_count / total, 3) if total > 0 else 0,
    }
