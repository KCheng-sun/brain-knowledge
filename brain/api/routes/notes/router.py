"""笔记业务域 API 路由。

端点:
  POST   /api/notes                 — 添加笔记
  GET    /api/notes/{note_id}/content — 笔记完整正文
  POST   /api/ingest                — 上传 Markdown 文件摄入
  GET    /api/status                — 知识库统计
  GET    /api/connections           — 查看关联
  GET    /api/tags                  — 标签浏览
  PATCH  /api/notes/{note_id}       — 编辑笔记标题/标签
  DELETE /api/connections/{conn_id} — 删除关联
"""

import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from brain.api.deps import get_metadata_store, get_pipeline, get_vector_store
from brain.api.routes.notes.models import (
    ConnectionItem,
    NoteAddRequest,
    NoteEditRequest,
    NoteResponse,
    StatusResponse,
)

router = APIRouter(prefix="/api", tags=["notes"])


@router.post("/notes", response_model=NoteResponse)
def add_note(req: NoteAddRequest):
    """快速添加笔记。"""
    note_id = get_pipeline().ingest_text_sync(req.text, title=req.title)
    return NoteResponse(note_id=note_id, message="摄入成功")


@router.get("/notes/{note_id}/content")
def get_note_content(note_id: str):
    """精确取回笔记完整正文（复习卡片展开用）。"""
    ms = get_metadata_store()
    note = ms.get_note(note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="笔记不存在")

    chunks = get_vector_store().get_note_chunks(note_id)
    content = "".join(c.content for c in chunks)
    return {
        "note_id": note_id,
        "title": note.title,
        "content": content,
        "ingested_at": note.ingested_at,
    }


@router.post("/ingest", response_model=NoteResponse)
def ingest_files(file: UploadFile = File(...)):
    """上传 Markdown 文件摄入。"""
    if not file.filename or not file.filename.endswith(".md"):
        return NoteResponse(note_id="", message="仅支持 .md 文件")

    content = file.file.read()
    tmp_path = Path(tempfile.gettempdir()) / f"brain_upload_{uuid.uuid4().hex[:8]}.md"
    tmp_path.write_bytes(content)

    try:
        note_id = get_pipeline().ingest_file_sync(tmp_path)
        return NoteResponse(note_id=note_id, message=f"已摄入: {file.filename}")
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


@router.get("/status", response_model=StatusResponse)
def get_status():
    """知识库统计概览。

    全部走批量 SQL（一次标签统计、一次关联、一次批量标签），无 N+1 查询。
    """
    ms = get_metadata_store()
    vs = get_vector_store()

    chunk_count = vs.count()
    note_count = ms.count_notes()

    # 一次 SQL：标签统计
    tag_counts = ms.get_tag_counts()

    # 一次 SQL：全部关联（含标题）
    flat_conns = ms.get_all_connections_flat()
    total_conns = len(flat_conns)
    all_conns = [
        {
            "source_title": c["source_title"],
            "target_title": c["target_title"],
            "relation_type": c["relation_type"],
            "description": c["description"],
            "strength": c["strength"],
        }
        for c in flat_conns
    ]

    top_tags = [
        {"name": name, "count": count}
        for name, count in sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    ]

    # 一次 SQL：最近笔记 + 批量标签
    recent = ms.list_notes(limit=5)
    tags_map = ms.get_tags_batch([n.id for n in recent])
    recent_notes = [
        {
            "note_id": note.id,
            "title": note.title,
            "date": note.ingested_at[:10] if note.ingested_at else "?",
            "tags": [t.name for t in tags_map.get(note.id, [])],
        }
        for note in recent
    ]

    return StatusResponse(
        note_count=note_count, chunk_count=chunk_count,
        tag_count=len(tag_counts), connection_count=total_conns,
        top_tags=top_tags, recent_notes=recent_notes, connections=all_conns,
    )


@router.get("/connections", response_model=list[ConnectionItem])
def get_connections():
    """获取所有关联（一次 SQL JOIN 查询）。"""
    ms = get_metadata_store()
    flat_conns = ms.get_all_connections_flat()
    return [
        ConnectionItem(
            source_title=c["source_title"],
            target_title=c["target_title"],
            relation_type=c["relation_type"],
            description=c["description"],
            strength=c["strength"],
        )
        for c in flat_conns
    ]


@router.get("/tags")
def list_tags():
    """列出全部标签及使用计数（FR35）。"""
    return get_metadata_store().list_all_tags()


@router.patch("/notes/{note_id}")
def edit_note(note_id: str, req: NoteEditRequest):
    """编辑笔记标题和标签（FR36）。内容编辑请重新摄入。"""
    from brain.models import TagCategory

    ms = get_metadata_store()
    note = ms.get_note(note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="笔记不存在")

    changed = []
    if req.title is not None:
        ms.update_note(note_id, title=req.title.strip())
        changed.append("title")

    for tag_name in req.add_tags:
        tag_id = ms.get_or_create_tag(
            name=tag_name.strip(), category=TagCategory.TOPIC, is_ai=False
        )
        ms.add_tag_to_note(note_id=note_id, tag_id=tag_id, confidence=1.0)
    if req.add_tags:
        changed.append(f"+{len(req.add_tags)}tags")

    for tag_name in req.remove_tags:
        ms.remove_tag_from_note(note_id, tag_name.strip())
    if req.remove_tags:
        changed.append(f"-{len(req.remove_tags)}tags")

    return {"note_id": note_id, "changed": changed or "none"}


@router.delete("/connections/{conn_id}")
def delete_connection(conn_id: int):
    """删除指定 ID 的关联（FR36）。"""
    ms = get_metadata_store()
    if not ms.delete_connection(conn_id):
        raise HTTPException(status_code=404, detail="关联不存在")
    return {"message": "已删除", "conn_id": conn_id}
