"""定时任务业务域的请求/响应模型。"""

from pydantic import BaseModel


class DigestResponse(BaseModel):
    content: str
