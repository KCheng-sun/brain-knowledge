"""数据源业务域的请求/响应模型。"""

from pydantic import BaseModel, Field


class WatchStatusResponse(BaseModel):
    running: bool
    watch_dir: str
    recent_events: list[dict]


class RssAddRequest(BaseModel):
    url: str = Field(..., min_length=1, description="RSS/Atom 订阅源 URL")


class RssFetchResponse(BaseModel):
    feeds_checked: int
    new_entries: int
    errors: list[str]


class BookmarkImportResponse(BaseModel):
    """书签导入响应（Phase 4B FR34）。"""
    total: int
    success: int
    skipped: int
    failed: int
