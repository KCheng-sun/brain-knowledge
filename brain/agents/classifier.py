"""分类 Agent — 深度分析笔记内容，生成多维标签。

使用 BaseAgent 框架，通过结构化 Prompt 让 LLM 输出分类结果，
经 Pydantic 验证后转为 Tag 列表存入 SQLite。
"""

from pydantic import BaseModel, Field

from brain.agents.base import BaseAgent
from brain.models import Tag, TagCategory


class TopicItem(BaseModel):
    """主题标签"""

    name: str = Field(description="主题名称，如 'AI Agent'、'Python'、'架构设计'")
    confidence: float = Field(description="置信度 [0.0, 1.0]")


class TypeItem(BaseModel):
    """内容类型标签"""

    name: str = Field(description="内容类型: 教程/观点/摘录/问题/总结/读书笔记")
    confidence: float = Field(description="置信度 [0.0, 1.0]")


class ClassificationOutput(BaseModel):
    """分类 Agent 的结构化输出"""

    topics: list[TopicItem] = Field(
        description="识别到的主题标签列表，按置信度降序，最多 5 个"
    )
    content_type: TypeItem = Field(description="内容类型")


class ClassifierAgent(BaseAgent):
    """分类 Agent — 分析笔记内容，输出主题标签 + 内容类型。"""

    name = "classifier"
    output_model = ClassificationOutput

    def build_user_prompt(self, note_title: str, content: str) -> str:
        return f"""请分析以下笔记内容并分类：

标题: {note_title}

内容:
{content[:3000]}

请输出 JSON 格式的分类结果。"""

    @staticmethod
    def to_tags(output: ClassificationOutput) -> list[Tag]:
        """将 LLM 输出转为 Tag 列表，供 MetadataStore 使用。"""
        tags: list[Tag] = []

        for t in output.topics:
            tags.append(
                Tag(
                    name=t.name,
                    category=TagCategory.TOPIC,
                    is_ai_generated=True,
                    confidence=t.confidence,
                )
            )

        tags.append(
            Tag(
                name=output.content_type.name,
                category=TagCategory.TYPE,
                is_ai_generated=True,
                confidence=output.content_type.confidence,
            )
        )

        return tags
