"""提示词业务域的请求/响应模型。"""

from pydantic import BaseModel, Field


class PromptUpdateRequest(BaseModel):
    content: str = Field(..., description="提示词正文")
    enabled: bool | None = Field(None, description="是否启用（不传则不变）")
