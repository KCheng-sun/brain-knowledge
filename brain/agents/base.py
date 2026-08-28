"""Agent 基类 — Agent 的统一入口。

提供：
  - 统一的 LLM 调用接口
  - 可选的结构化输出（output_model 非 None 时用 with_structured_output）
  - 日志记录

结构化输出（output_model 非 None 时启用）：
  - with_structured_output(method="function_calling")
  - DeepSeek 实测支持 function_calling（json_mode 需 prompt 含 'json' 字样，不如 fc 干净）
  - LLM 在生成时就遵循 schema，invoke 直接返回 Pydantic 实例，无需解析
  - HTTP 层瞬时错误（429/5xx/超时）由 SDK 原生 max_retries 重试

纯文本输出（output_model = None）：
  - 普通 llm.invoke，返回 AIMessage，子类自行处理 response.content
  - 适用于摘要、改写等需要自由文本的场景
"""

from typing import TypeVar

from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger
from pydantic import BaseModel

from brain.llm import get_chat_model

T = TypeVar("T", bound=BaseModel)


class BaseAgent:
    """Agent 基类。

    子类定义：
      - name: Agent 名称（用于日志 + 提示词库的 prompt_key）
      - build_user_prompt(...): 构建用户提示词
      - output_model: 期望的 Pydantic 输出模型；None 表示纯文本输出（不结构化）

    system_prompt 从 prompts 表读取（Phase 5E），key = self.name。

    调用 self.run(...) 返回值：
      - output_model 非 None：结构化的 Pydantic 实例
      - output_model 为 None：AIMessage（子类取 .content 获得文本）
    """

    name: str = "base"
    # None = 纯文本模式（普通 invoke）；设为 Pydantic 模型类 = 结构化模式
    output_model: type[T] | None = None
    # 结构化模式用的 method：function_calling（DeepSeek 实测稳定支持）
    _structured_method: str = "function_calling"

    @property
    def system_prompt(self) -> str:
        """从 prompts 表读取系统提示词（key=self.name）。"""
        from brain.prompts import get_prompt

        return get_prompt(self.name)

    def build_user_prompt(self, **kwargs) -> str:
        """构建用户提示词。子类必须实现。"""
        raise NotImplementedError

    def run(self, **kwargs):
        """执行 Agent。

        - output_model 非 None：用 with_structured_output，返回 Pydantic 实例
        - output_model 为 None：普通 invoke，返回 AIMessage

        HTTP 层瞬时错误（429/5xx/超时）由 SDK 原生 max_retries 重试，无需应用层重试。
        """
        user_prompt = self.build_user_prompt(**kwargs)
        llm = get_chat_model()

        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=user_prompt),
        ]

        if self.output_model is not None:
            # 结构化模式：function calling 在生成时强制 schema，invoke 直接返回 Pydantic 实例
            structured_llm = llm.with_structured_output(
                self.output_model, method=self._structured_method
            )
            result = structured_llm.invoke(messages)
        else:
            # 纯文本模式：普通 invoke，返回 AIMessage
            result = llm.invoke(messages)

        logger.info(f"[{self.name}] ✓ 执行成功")
        return result
