"""语义搜索业务域 API 路由。

端点:
  GET /api/search — 语义搜索 + 标签过滤
"""

from fastapi import APIRouter, Query

from brain.api.deps import get_metadata_store, get_vector_store
from brain.api.routes.search.models import SearchResponse, SearchResultItem

router = APIRouter(prefix="/api", tags=["search"])


@router.get("/search", response_model=SearchResponse)
def search_notes(
    query: str = Query(..., min_length=1),
    tag: str | None = Query(None),
    top_k: int = Query(5, ge=1, le=20),
):
    """语义搜索 + 标签过滤。"""
    ms = get_metadata_store()
    vs = get_vector_store()

    tag_note_ids: set | None = None
    if tag:
        all_notes = ms.list_notes(limit=10000)
        tag_note_ids = set()
        for note in all_notes:
            note_tags = ms.get_note_tags(note.id)
            if any(tag.lower() in t.name.lower() for t in note_tags):
                tag_note_ids.add(note.id)

    results = vs.search(query, top_k=max(top_k * 2, 20))

    items = []
    seen = set()
    for r in results:
        if tag_note_ids is not None and r.note_id not in tag_note_ids:
            continue
        if r.note_id in seen:
            continue
        seen.add(r.note_id)
        if len(items) >= top_k:
            break

        note_tags = ms.get_note_tags(r.note_id)
        tag_names = [t.name for t in note_tags]

        items.append(SearchResultItem(
            rank=len(items) + 1,
            score=round(r.score, 4),
            title=r.note_title,
            content_preview=r.content[:300],
            note_id=r.note_id,
            tags=tag_names,
        ))

    return SearchResponse(query=query, total=len(items), results=items)
