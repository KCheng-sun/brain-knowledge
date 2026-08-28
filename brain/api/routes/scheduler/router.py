"""定时任务业务域 API 路由（调度 / 摘要报告 / 知识图谱）。

端点:
  GET  /api/scheduler          — 定时任务状态
  POST /api/scheduler/run/{name} — 手动执行任务
  GET  /api/digest/reports     — 摘要报告列表
  GET  /api/graph              — 知识图谱数据
  GET  /api/digest             — 生成知识摘要
"""

from fastapi import APIRouter, HTTPException, Query

from brain.api.deps import get_metadata_store, get_scheduler
from brain.api.routes.scheduler.models import DigestResponse
from brain.services.digest import DigestService

router = APIRouter(prefix="/api", tags=["scheduler"])


@router.get("/scheduler")
def scheduler_status():
    """查询定时任务状态。"""
    scheduler = get_scheduler()
    if scheduler is None:
        return []
    return scheduler.get_status()


@router.post("/scheduler/run/{task_name}")
def scheduler_run_now(task_name: str):
    """手动立即执行某定时任务。

    task_name: rss_sync | daily_digest | weekly_digest
    """
    scheduler = get_scheduler()
    if scheduler is None:
        raise HTTPException(status_code=503, detail="调度器未初始化")

    result = scheduler.run_now(task_name)
    if result is None:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_name}")
    return {"task": task_name, "result": result}


@router.get("/digest/reports")
def digest_reports(limit: int = Query(10, ge=1, le=50)):
    """列出最近生成的摘要报告（定时任务产物）。"""
    return get_metadata_store().list_digest_reports(limit=limit)


@router.get("/graph")
def knowledge_graph():
    """知识图谱数据——笔记节点 + 关联边。

    全部走批量 SQL（一次取关联、一次取度数、一次取标签），
    无 N+1 查询，500+ 笔记时依然毫秒级响应。
    """
    ms = get_metadata_store()

    # 一次 SQL：全部关联 + 两端标题
    flat_conns = ms.get_all_connections_flat()

    edges = [
        {
            "source": c["source"],
            "target": c["target"],
            "relation_type": c["relation_type"],
            "strength": c["strength"],
            "description": c["description"],
        }
        for c in flat_conns
    ]

    # 一次 SQL：度数统计
    degree_map = ms.get_note_degree_map()

    # 一次 SQL：全部笔记 + 批量标签
    all_notes = ms.list_notes(limit=10000)
    tags_map = ms.get_tags_batch([n.id for n in all_notes])

    nodes = [
        {
            "id": note.id,
            "title": note.title[:30],
            "tags": [t.name for t in tags_map.get(note.id, [])][:3],
            "degree": degree_map.get(note.id, 0),
            "date": note.ingested_at[:10] if note.ingested_at else "",
        }
        for note in all_notes
    ]

    return {"nodes": nodes, "edges": edges}


@router.get("/digest", response_model=DigestResponse)
def get_digest(weekly: bool = Query(False)):
    """生成知识摘要。"""
    svc = DigestService(get_metadata_store())
    result = svc.daily_sync() if not weekly else svc.weekly_sync()
    return DigestResponse(content=result)
