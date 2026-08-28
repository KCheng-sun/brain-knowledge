"""复习业务域的请求/响应模型。"""

from pydantic import BaseModel, Field


class ReviewRecordRequest(BaseModel):
    note_id: str = Field(..., description="笔记 ID")
    quality: int = Field(..., ge=0, le=5, description="0-5 评分（0-2忘记/3困难/4良好/5简单）")
