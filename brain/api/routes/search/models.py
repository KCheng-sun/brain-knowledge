"""语义搜索业务域的请求/响应模型。"""

from pydantic import BaseModel


class SearchResultItem(BaseModel):
    rank: int
    score: float
    title: str
    content_preview: str
    note_id: str
    tags: list[str]


class SearchResponse(BaseModel):
    query: str
    total: int
    results: list[SearchResultItem]
