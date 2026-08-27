"""Agent 基类 — 所有 DeepAgents 的统一入口。

提供：
  - 统一的 LLM 调用接口
  - 结构化 JSON 输出的解析和 Pydantic 验证
  - 指数退避重试
  - 日志记录
"""

import json
import re
import time
from typing import TypeVar

from loguru import logger
from pydantic import BaseModel

from brain.llm import get_chat_model

T = TypeVar("T", bound=BaseModel)


class BaseAgent:
    """Agent 基类。

    子类只需定义：
      - name: Agent 名称（用于日志 + 提示词库的 prompt_key）
      - build_user_prompt(...): 构建用户提示词
      - output_model: 期望的 Pydantic 输出模型

    system_prompt 从 prompts 表读取（Phase 5E），key = self.name。
    然后调用 self.run(input_data) 即可获得验证后的结构化输出。
    """

    name: str = "base"
    output_model: type[T] = BaseModel  # 子类必须覆写
    max_retries: int = 3
    retry_delay: float = 1.0  # 秒

    @property
    def system_prompt(self) -> str:
        """从 prompts 表读取系统提示词（key=self.name）。"""
        from brain.prompts import get_prompt

        return get_prompt(self.name)

    @property
    def _output_example(self) -> str:
        """返回输出示例 JSON 字符串。子类应覆写。"""
        return json.dumps(self._build_example(self.output_model), ensure_ascii=False, indent=2)

    def build_user_prompt(self, **kwargs) -> str:
        """构建用户提示词。子类必须实现。"""
        raise NotImplementedError

    def run(self, **kwargs) -> T:
        """执行 Agent，返回 Pydantic 模型实例。

        自动处理：JSON 提取、Pydantic 验证、失败重试。
        """
        from langchain_core.messages import HumanMessage, SystemMessage

        user_prompt = self.build_user_prompt(**kwargs)
        llm = get_chat_model()

        last_error = None
        for attempt in range(1, self.max_retries + 1):
            try:
                messages = [
                    SystemMessage(content=self.system_prompt),
                    HumanMessage(content=self._build_user_prompt_with_schema(user_prompt)),
                ]
                response = llm.invoke(messages)
                parsed = self._parse_json(response.content)
                result = self.output_model(**parsed)
                logger.info(f"[{self.name}] ✓ 执行成功 (attempt {attempt})")
                return result
            except Exception as e:
                last_error = e
                if attempt < self.max_retries:
                    wait = self.retry_delay * (2 ** (attempt - 1))
                    logger.warning(
                        f"[{self.name}] 第 {attempt} 次失败: {e}，{wait}s 后重试..."
                    )
                    time.sleep(wait)
                else:
                    logger.error(f"[{self.name}] ✗ 全部 {self.max_retries} 次重试失败: {e}")

        raise RuntimeError(f"[{self.name}] 执行失败: {last_error}")

    def _build_user_prompt_with_schema(self, user_prompt: str) -> str:
        """在 user 消息中附加 JSON 格式约束和示例（system 角色已分离）。"""
        schema_desc = self._describe_model(self.output_model)
        example = self._output_example
        return f"""{user_prompt}

---
重要：你必须严格按照以下 JSON Schema 输出，不要输出任何其他内容。

格式定义：
{schema_desc}

正确输出示例：
{example}

规则：
1. 每个字段的类型必须和格式定义一致，不能把对象写成字符串
2. 数组元素必须是对象（如果有 name/confidence 等字段）
3. 只输出 JSON，不要用 ```json``` 包裹"""

    @staticmethod
    def _parse_json(text: str) -> dict:
        """从 LLM 输出中提取 JSON 对象。

        处理常见情况：
          - 纯 JSON
          - JSON 被 ```json ... ``` 包裹
          - JSON 前后有说明文字
        """
        text = text.strip()

        # 尝试移除 markdown 代码块
        if text.startswith("```"):
            end = text.rfind("```")
            if end > 3:
                text = text[3:end].strip()
            # 去掉可能的 ```json 标记
            if text.startswith("json"):
                text = text[4:].strip()

        # 如果还不是 JSON，尝试用正则提取 {}
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            text = match.group(0)

        return json.loads(text)

    @staticmethod
    def _build_example(model: type[BaseModel]) -> dict:
        """从模型字段生成一个合理的示例值，用于 prompt 中的示例。"""
        example = {}
        for field_name, field_info in model.model_fields.items():
            annotation = field_info.annotation
            example[field_name] = _example_value(annotation)
        return example

    @staticmethod
    def _describe_model(model: type[BaseModel], indent: int = 0) -> str:
        """将 Pydantic 模型描述为 JSON Schema 风格的字符串，放入 prompt 中。

        不做完整的 JSON Schema 生成，只做人类可读的字段描述。
        """
        prefix = "  " * indent
        lines = [f"{prefix}{{"]
        for field_name, field_info in model.model_fields.items():
            annotation = field_info.annotation
            type_name = _type_to_str(annotation)
            description = field_info.description or ""
            desc_str = f" // {description}" if description else ""
            lines.append(f"{prefix}  \"{field_name}\": {type_name},{desc_str}")
        lines.append(f"{prefix}}}")
        return "\n".join(lines)


def _example_value(annotation) -> object:
    """从类型注解递归构建示例值。"""
    import typing

    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)

    # list[X] → [example(X)]
    if origin is list:
        inner = args[0] if args else str
        return [_example_value(inner)]

    # Pydantic 模型 → 递归构建
    if isinstance(annotation, type) and issubclass(annotation, BaseModel) and annotation is not BaseModel:
        return _build_example_static(annotation)

    if annotation is str:
        return "示例字符串"
    if annotation is int:
        return 42
    if annotation is float:
        return 0.95
    if annotation is bool:
        return True

    return "示例"


def _build_example_static(model: type) -> dict:
    """静态函数版本，供 _example_value 递归调用。"""
    example = {}
    for field_name, field_info in model.model_fields.items():
        annotation = field_info.annotation
        example[field_name] = _example_value(annotation)
    return example


def _type_to_str(annotation) -> str:
    """将 Python 类型转为 JSON Schema 风格的类型名。"""
    import typing

    origin = typing.get_origin(annotation)
    if origin is list:
        args = typing.get_args(annotation)
        if args:
            return f"[{_type_to_str(args[0])}, ...]"
        return "[...]"
    if origin is dict:
        return "{key: value, ...}"
    if annotation is str:
        return "string"
    if annotation is int:
        return "number"
    if annotation is float:
        return "number"
    if annotation is bool:
        return "boolean"
    return "string"
