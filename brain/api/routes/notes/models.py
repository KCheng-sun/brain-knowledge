"""笔记业务域的请求/响应模型。"""

from pydantic import BaseModel, Field


class NoteAddRequest(BaseModel):
    text: str = Field(..., min_length=1, description="笔记内容")
    title: str | None = Field(None, description="标题")


class NoteResponse(BaseModel):
    note_id: str
    message: str


class NoteEditRequest(BaseModel):
    """笔记编辑请求（Phase 4B FR36）。"""
    title: str | None = Field(None, description="新标题")
    add_tags: list[str] = Field(default_factory=list, description="要添加的标签名")
    remove_tags: list[str] = Field(default_factory=list, description="要移除的标签名")


class StatusResponse(BaseModel):
    """知识库统计概览。"""
    note_count: int
    chunk_count: int
    tag_count: int
    connection_count: int
    top_tags: list[dict]
    recent_notes: list[dict]
    connections: list[dict]


class ConnectionItem(BaseModel):
    source_title: str
    target_title: str
    relation_type: str
    description: str | None
    strength: float
