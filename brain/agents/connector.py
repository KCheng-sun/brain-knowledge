"""关联发现 Agent — 发现新笔记与已有笔记之间的隐性关联。

流程:
  1. 向量相似度粗筛 → Top N 候选笔记
  2. 用 LLM 深度分析每对候选，判断是否真正相关
  3. 确定关系类型 + 生成关联描述
  4. 返回 Connection 列表
"""

from pydantic import BaseModel, Field

from brain.agents.base import BaseAgent
from brain.models import Connection, RelationType


class ConnectionItem(BaseModel):
    """单条关联发现结果"""

    target_note_id: str = Field(description="关联到的已有笔记 ID")
    target_title: str = Field(description="关联笔记的标题")
    relation_type: str = Field(
        description="关联类型: related(一般相关) | extends(延续扩展) | contradicts(观点矛盾) | references(引用)"
    )
    strength: float = Field(description="关联强度 [0.0, 1.0]")
    description: str = Field(description="关联说明，一句话解释两者关系")


class ConnectionOutput(BaseModel):
    """关联发现 Agent 的结构化输出"""

    connections: list[ConnectionItem] = Field(
        description="发现的关联列表。若没有有意义的关联，返回空列表。"
    )


class ConnectorAgent(BaseAgent):
    """关联发现 Agent — 深度分析新笔记与候选笔记的语义关系。"""

    name = "connector"
    output_model = ConnectionOutput

    def build_user_prompt(
        self,
        new_note_title: str,
        new_note_content: str,
        candidates: list[dict],
    ) -> str:
        """构建提示词。

        Args:
            new_note_title: 新笔记标题
            new_note_content: 新笔记内容（截断到 2000 字符）
            candidates: 候选笔记列表 [{"note_id": ..., "title": ..., "content": ...}]
        """
        candidate_texts = []
        # 只取前 10 个候选，每个截断到 200 字符——避免 prompt 过长
        for i, c in enumerate(candidates[:10], 1):
            content_preview = c["content"][:200]
            candidate_texts.append(
                f"候选 {i}: id={c['note_id']}, 标题={c['title']}\n内容: {content_preview}..."
            )

        candidates_block = "\n\n".join(candidate_texts)

        return f"""新笔记:
标题: {new_note_title}
内容: {new_note_content[:1000]}

候选笔记（需要逐一判断是否与新笔记有关联）:
{candidates_block}

请分析新笔记与每篇候选笔记的关系，输出 JSON。"""

    @staticmethod
    def to_connections(
        output: ConnectionOutput,
        source_note_id: str,
    ) -> list[Connection]:
        """将 LLM 输出转为 Connection 列表。"""
        connections = []
        for item in output.connections:
            try:
                relation_type = RelationType(item.relation_type)
            except ValueError:
                relation_type = RelationType.RELATED

            connections.append(
                Connection(
                    source_note_id=source_note_id,
                    target_note_id=item.target_note_id,
                    relation_type=relation_type,
                    strength=item.strength,
                    description=item.description,
                    is_ai_generated=True,
                )
            )
        return connections
