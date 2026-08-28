"""评估闭环业务域的请求/响应模型。"""

from pydantic import BaseModel, Field


class EvalFeedbackRequest(BaseModel):
    trace_id: str | None = Field(None, description="问答的 trace_id（便于回溯）")
    question: str = Field(..., description="用户问题")
    answer: str = Field(..., description="Agent 回答")
    reason: str = Field("user_thumbs_down", description="点踩原因")


class GoldenCaseRequest(BaseModel):
    id: str = Field(..., description="用例 ID，如 eval_001")
    question: str = Field(..., description="问题")
    expected_keywords: list[str] = Field(default_factory=list, description="期望关键词")
    expected_sources: list[str] = Field(default_factory=list, description="期望引用笔记 id")
    min_score: float = Field(0.7, ge=0, le=1.0, description="及格分")
    enabled: bool = Field(True, description="是否启用")
