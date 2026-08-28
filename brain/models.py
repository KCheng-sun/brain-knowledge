"""核心数据模型——项目中所有 Pydantic 模型的唯一定义处。

所有 ID 使用 UUID4 字符串。时间戳使用 ISO 8601 格式。
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

# ============================================================
# 枚举类型
# ============================================================


class SourceType(str, Enum):
    """笔记来源类型"""

    MARKDOWN = "markdown"
    CLI = "cli"
    RSS = "rss"
    BOOKMARK = "bookmark"


class NoteStatus(str, Enum):
    """笔记状态"""

    ACTIVE = "active"
    ARCHIVED = "archived"
    DELETED = "deleted"


class TagCategory(str, Enum):
    """标签分类维度"""

    TOPIC = "topic"  # 主题（技术/商业/生活…）
    TYPE = "type"  # 内容类型（教程/观点/摘录/问题…）
    LANGUAGE = "language"  # 语言
    DIFFICULTY = "difficulty"  # 难度


class RelationType(str, Enum):
    """笔记关联类型"""

    RELATED = "related"  # 一般相关
    EXTENDS = "extends"  # 延续/扩展
    CONTRADICTS = "contradicts"  # 观点矛盾
    REFERENCES = "references"  # 引用


# ============================================================
# 笔记相关模型
# ============================================================


class NoteMetadata(BaseModel):
    """笔记元数据，对应 PostgreSQL notes 表"""

    id: str = Field(default_factory=lambda: _new_uuid())
    title: str
    source_type: SourceType
    source_path: str | None = None
    file_hash: str | None = None
    content_preview: str = ""
    content_length: int = 0
    chunk_count: int = 0
    status: NoteStatus = NoteStatus.ACTIVE
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    ingested_at: str | None = None


class Chunk(BaseModel):
    """笔记的文本分块"""

    id: str = Field(default_factory=lambda: _new_uuid())
    note_id: str
    index: int  # 分块在笔记中的序号（从 0 开始）
    content: str
    token_count: int = 0
    metadata: dict = Field(default_factory=dict)  # 透传给向量库的元数据


class ParsedDocument(BaseModel):
    """解析后的文档——接入层统一输出格式"""

    file_path: str | None = None
    title: str
    content: str  # 纯文本内容（Markdown 已转纯文本）
    frontmatter: dict = Field(default_factory=dict)  # YAML frontmatter 解析结果
    file_hash: str | None = None  # SHA256，用于检测文件变更


# ============================================================
# 标签 & 关联
# ============================================================


class Tag(BaseModel):
    """标签"""

    id: int | None = None  # 数据库自增 ID
    name: str
    category: TagCategory
    is_ai_generated: bool = False
    confidence: float | None = None  # AI 标签的置信度 [0.0, 1.0]


class Connection(BaseModel):
    """笔记之间的关联"""

    id: int | None = None  # 数据库自增 ID
    source_note_id: str
    target_note_id: str
    relation_type: RelationType
    strength: float = 0.5  # 关联强度 [0.0, 1.0]
    description: str | None = None  # AI 生成的关联说明
    is_ai_generated: bool = False
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


# ============================================================
# 检索 & 问答
# ============================================================


class SearchResult(BaseModel):
    """单条搜索结果"""

    chunk_id: str
    note_id: str
    note_title: str
    content: str
    score: float  # 相似度分数 [0.0, 1.0]
    metadata: dict = Field(default_factory=dict)


class ResearchResult(BaseModel):
    """深度问答结果"""

    question: str
    answer: str
    sources: list[dict] = Field(
        default_factory=list
    )  # [{"note_id": ..., "title": ..., "excerpt": ...}]
    confidence: float = 0.0


# ============================================================
# 摘要模型（Phase 2+ 正式使用）
# ============================================================


class Digest(BaseModel):
    """每日知识摘要"""

    date: str
    new_notes_count: int
    new_tags: list[Tag] = Field(default_factory=list)
    new_connections: list[Connection] = Field(default_factory=list)
    highlights: str = ""  # AI 生成的摘要文字


# ============================================================
# 内部工具
# ============================================================


def _new_uuid() -> str:
    """生成 UUID4 短格式 ID（12 位）。"""
    import uuid

    return uuid.uuid4().hex[:12]
