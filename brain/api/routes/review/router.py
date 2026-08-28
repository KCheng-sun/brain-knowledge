"""复习业务域 API 路由（SM-2）。

端点:
  GET  /api/review         — 到期复习列表
  POST /api/review/record  — 记录复习评分
"""

from fastapi import APIRouter, Query

from brain.api.deps import get_metadata_store
from brain.api.routes.review.models import ReviewRecordRequest
from brain.services.review import ReviewService

router = APIRouter(prefix="/api/review", tags=["review"])


@router.get("")
def get_review(limit: int = Query(10, ge=1, le=50)):
    """SM-2 到期复习列表（含未进入系统的新卡片）。"""
    svc = ReviewService(get_metadata_store())
    due = svc.get_due_items_sync(limit=limit)
    return {"total": len(due), "items": due}


@router.post("/record")
def record_review(req: ReviewRecordRequest):
    """记录复习评分，SM-2 计算下次复习时间。"""
    svc = ReviewService(get_metadata_store())
    return svc.record_review_sync(req.note_id, req.quality)
