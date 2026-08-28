"""可观测性业务域 API 路由（健康检查 / 指标 / 成本）。

端点:
  GET /api/health              — 健康检查
  GET /api/metrics/summary     — 指标汇总（看板）
  GET /api/metrics/traces      — 最近调用链
  GET /api/metrics/traces/{id} — 单条调用链详情
  GET /api/cost/summary        — 成本汇总
  GET /api/cost/by-model       — 按模型聚合成本
  GET /api/cost/by-day         — 按日聚合成本
"""

from fastapi import APIRouter, Query

from brain.api.deps import get_metadata_store, get_vector_store
from brain.embedding import get_embedding_fn

router = APIRouter(prefix="/api", tags=["observability"])


@router.get("/health")
def get_health():
    """健康检查——探测 LLM/Embedding/SQLite/ChromaDB 连通性。

    LLM 探测默认跳过（避免烧配额），仅 dry_run 时真调。
    Embedding 探测用空字符串，不消耗有意义配额。
    """
    from brain.observability import check_health

    ms = get_metadata_store()
    vs = get_vector_store()
    # embedding_fn 懒加载传入（避免在 health 检查外初始化）
    try:
        embedding_fn = get_embedding_fn()
    except Exception:
        embedding_fn = None
    return check_health(ms, vs, embedding_fn)


@router.get("/metrics/summary")
def get_metrics_summary(hours: int = Query(24, ge=1, le=168, description="统计时间窗口（小时）")):
    """指标汇总（看板用）。"""
    return get_metadata_store().get_metrics_summary(hours=hours)


@router.get("/metrics/traces")
def get_recent_traces(limit: int = Query(20, ge=1, le=100)):
    """最近问答调用链列表。"""
    return get_metadata_store().get_recent_traces(limit=limit)


@router.get("/metrics/traces/{trace_id}")
def get_trace_detail(trace_id: str):
    """某条 trace 的完整调用链。

    返回两个部分：
      - events: trace_events 表的完整调用日志（LLM 请求响应、工具入参出参）
      - metrics: metrics 表的数值指标（latency/token/count）
    """
    ms = get_metadata_store()
    return {
        "events": ms.get_trace_events(trace_id),
        "metrics": ms.get_trace_detail(trace_id),
    }


# ============================================================
# 成本治理（Phase 5B FR49）
# ============================================================

@router.get("/cost/summary")
def get_cost_summary():
    """成本汇总（今日/本月/总累计 + 配额用量）。"""
    from brain.observability import check_budget

    ms = get_metadata_store()
    summary = ms.get_cost_summary()
    budget = check_budget(ms)
    return {**summary, "budget": budget}


@router.get("/cost/by-model")
def get_cost_by_model(hours: int = Query(24, ge=1, le=720)):
    """按模型聚合成本。"""
    return get_metadata_store().get_cost_by_model(hours=hours)


@router.get("/cost/by-day")
def get_cost_by_day(days: int = Query(30, ge=1, le=365)):
    """按日聚合成本趋势。"""
    return get_metadata_store().get_cost_by_day(days=days)
