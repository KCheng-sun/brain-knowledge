"""深度问答业务域的请求/响应模型。"""

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1)
    session_id: str | None = Field(None, description="会话 ID（不传则自动创建新会话）")


class AskResponse(BaseModel):
    question: str
    answer: str


class ResumeRequest(BaseModel):
    session_id: str = Field(..., description="会话 ID（thread_id）")
    decisions: list[dict] = Field(
        ...,
        description='HIL 决策列表，如 [{"type": "approve"}] 或 [{"type": "reject", "message": "..."}]',
    )


class SessionCreateRequest(BaseModel):
    title: str | None = None


class SessionItem(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str


class MessageItem(BaseModel):
    id: int
    role: str
    content: str
    timeline: list = []
    created_at: str


class SessionMessagesResponse(BaseModel):
    session_id: str
    title: str
    messages: list[MessageItem]
