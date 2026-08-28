# 个人知识管家（第二大脑）— 项目设计文档

> 版本: v0.5.0
> 最后更新: 2024-08-13
> 状态: Phase 1-3 已完成，Phase 4 进行中，Phase 5 设计中
> 依赖文档: [需求文档](./requirements.md)

---

## 1. 设计目标

1. **本地优先** — 核心功能不依赖云服务，除 LLM API 调用外
2. **文档驱动** — 需求→设计→实现，每次迭代先更新文档
3. **渐进增强** — Phase 1 做最小可用，每个 Phase 增加一层智能
4. **可测试** — 每个模块可独立测试，核心路径有集成测试

---

## 2. 总体架构

```
┌─────────────────────────────────────────────────────────────┐
│                        CLI / API 层                          │
│  brain add | search | ask | digest | config                  │
│  (Click/Typer)                                               │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                     服务层 (Services)                         │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────────────────┐ │
│  │ DigestService│  │ReviewService│  │ IngestionOrchestrator│ │
│  │ 每日/周摘要  │  │ 间隔重复    │  │ 摄入编排             │ │
│  └─────────────┘  └─────────────┘  └──────────────────────┘ │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                 智能处理层 (Agents)                            │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐   │
│  │Classifier │ │Connector │ │Synthesizer│ │Researcher   │   │
│  │ 分类 Agent│ │ 关联 Agent│ │ 摘要 Agent│ │ 问答 Agent   │   │
│  │DeepAgents │ │DeepAgents│ │DeepAgents│ │DeepAgents   │   │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────┘   │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                  流水线层 (LangGraph)                          │
│  ┌────────────────────────────────────────────────────────┐ │
│  │              IngestionPipeline (摄入流水线)              │ │
│  │  解析 → 分块 → 嵌入 → 分类 → 索引 → 关联发现            │ │
│  │  (每个节点是一个 LangGraph Node, 状态可持久化)          │ │
│  └────────────────────────────────────────────────────────┘ │
│  ┌────────────────────────────────────────────────────────┐ │
│  │              QueryRouter (查询路由)                      │ │
│  │  意图识别 → 搜索策略选择 → 执行 → 结果合成              │ │
│  └────────────────────────────────────────────────────────┘ │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                    存储层 (Storage)                           │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────────────┐ │
│  │ pgvector     │ │ PostgreSQL   │ │ NetworkX Graph       │ │
│  │ 向量存储     │ │ 元数据/标签  │ │ 知识图谱（轻量）     │ │
│  │ 语义检索     │ │ CRUD 操作    │ │ 关联关系             │ │
│  └──────────────┘ └──────────────┘ └──────────────────────┘ │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                 接入层 (Ingestion Sources)                    │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐   │
│  │ 文件监听 │ │CLI 输入  │ │RSS 拉取  │ │ 书签导入     │   │
│  │(watchdog)│ │          │ │(feedparser)│ │(JSON parse) │   │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. 技术选型

### 3.1 核心框架

| 组件 | 选型 | 选型理由 |
|------|------|----------|
| **LLM 编排** | LangChain | 成熟的文档加载器、文本分割器、Embeddings 抽象、Tool 定义 |
| **流程控制** | LangGraph | 有状态的图流水线、Checkpoint 持久化、Human-in-the-Loop |
| **多 Agent** | DeepAgents | 层次化 Agent 调度、深度推理、可插拔 Agent 定义 |
| **LLM** | Claude API (claude-fable-5) | 最强推理能力，适合深度分类/关联/问答 |
| **Embedding** | sentence-transformers (BGE-large-zh) | 本地运行、1024 维、中文优化 |

### 3.2 存储

| 组件 | 选型 | 用途 | Phase |
|------|------|------|-------|
| **关系型数据库** | PostgreSQL 17 | 笔记元数据、标签、摄入日志、会话、指标等全部业务数据 | P0 |
| **向量检索** | pgvector（PostgreSQL 扩展） | 语义检索（笔记分块/对话记忆/知识片段向量） | P0 |
| **检查点** | PostgresSaver（LangGraph） | HIL 中断恢复、会话状态持久化 | P0 |
| **图存储** | NetworkX | 知识图谱关联（内存图，JSON 持久化） | P1 |
| **文件系统** | 本地目录 `data/notes/` | Markdown 笔记原始文件 | P0 |

> **统一存储**：业务元数据 + 向量检索 + Checkpoint 全部存在一个 PostgreSQL 库（brain），
> 便于备份（`pg_dump brain`）和事务一致。表名按层级加前缀区分（见 4.1）。

#### 表命名约定（三层）

| 层级 | 表名前缀 | 示例 | 创建者 |
|------|---------|------|--------|
| 业务元数据 | 无（主体） | `notes`、`sessions`、`messages` | MetadataStore |
| 向量检索 | `vec_` | `vec_note_chunks`、`vec_conversation_memory` | VectorStore |
| 检查点 | `checkpoint_` | `checkpoints`、`checkpoint_blobs` | LangGraph PostgresSaver |

所有表和关键字段均带 `COMMENT ON` 注释，数据库可直接查看用途。

### 3.3 工具库

| 用途 | 选型 |
|------|------|
| CLI 框架 | Click (轻量，够用) |
| 文件监听 | watchdog |
| Markdown 解析 | markdown-it-py / Python markdown |
| RSS 解析 | feedparser |
| 配置管理 | PyYAML + pydantic-settings |
| 日志 | loguru |
| 测试 | pytest + pytest-asyncio |
| 代码质量 | ruff (lint + format) |

---

## 4. 模块详细设计

### 4.1 存储层 (`brain/storage/`)

#### 4.1.1 VectorStore (`vector_store.py`)

```python
class VectorStore:
    """pgvector 封装——向量检索层"""
    # 三张表（vec_ 前缀）：
    #   vec_note_chunks        笔记分块向量
    #   vec_conversation_memory 对话消息向量（第二层记忆）
    #   vec_fragment_memory     知识片段向量（第三层记忆）
    embedding_fn: Callable  # BGE-large-zh, 1024 维

    def add(chunks: list[Chunk]) -> list[str]
        # 将分块嵌入后存入 pgvector

    def search(query: str, top_k: int = 10) -> list[SearchResult]
        # 语义搜索，返回带相似度分数的结果

    def delete_by_note(note_id: str) -> None
        # 按笔记 ID 删除全部分块向量
```

#### 4.1.2 MetadataStore (`metadata.py`)

```python
class MetadataStore:
    """PostgreSQL 元数据管理——业务层（19 张表，无前缀）"""
    
    def create_note(meta: NoteMetadata) -> str
    def get_note(note_id: str) -> NoteMetadata | None
    async def update_note(note_id: str, updates: dict) -> None
    def delete_note(note_id: str) -> None
    def list_notes(
        tags: list[str] = None,
        date_from: datetime = None,
        date_to: datetime = None,
        limit: int = 50
    ) -> list[NoteMetadata]
    def add_tags(note_id: str, tags: list[Tag]) -> None
    def add_connection(conn: Connection) -> None
    def get_connections(note_id: str) -> list[Connection]
```

**PostgreSQL Schema（核心表，完整定义见 `metadata.py:_create_tables`）：**

```sql
-- 笔记元数据表
CREATE TABLE notes (
    id TEXT PRIMARY KEY,          -- UUID
    title TEXT NOT NULL,
    source_type TEXT NOT NULL,    -- 'markdown' | 'cli' | 'rss' | 'bookmark'
    source_path TEXT,             -- 原始文件路径
    file_hash TEXT,               -- SHA256, 用于检测文件变更
    content_preview TEXT,         -- 前 200 字符
    content_length INTEGER,
    chunk_count INTEGER,
    status TEXT DEFAULT 'active', -- 'active' | 'archived' | 'deleted'
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    ingested_at TEXT
);

-- 标签表
CREATE TABLE tags (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL,       -- 'topic' | 'type' | 'language' | 'difficulty'
    is_ai_generated BOOLEAN DEFAULT 0
);

-- 笔记-标签关联表
CREATE TABLE note_tags (
    note_id TEXT NOT NULL,
    tag_id INTEGER NOT NULL,
    confidence REAL,              -- AI 标签的置信度
    PRIMARY KEY (note_id, tag_id)
);

-- 关联表
CREATE TABLE connections (
    id SERIAL PRIMARY KEY,
    source_note_id TEXT NOT NULL,
    target_note_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,  -- 'related' | 'extends' | 'contradicts' | 'references'
    strength REAL DEFAULT 0.5,
    description TEXT,             -- AI 生成的关联说明
    created_at TEXT NOT NULL,
    is_ai_generated BOOLEAN DEFAULT 0
);

-- 摄入日志表
CREATE TABLE ingestion_log (
    id SERIAL PRIMARY KEY,
    note_id TEXT NOT NULL,
    event TEXT NOT NULL,          -- 'parsed' | 'chunked' | 'embedded' | 'classified' | 'connected'
    status TEXT NOT NULL,         -- 'success' | 'error'
    message TEXT,
    duration_ms INTEGER,
    timestamp TEXT NOT NULL
);
```

#### 4.1.3 GraphStore (`graph_store.py`)

```python
class GraphStore:
    """NetworkX 知识图谱 — Phase 2 引入"""
    graph: nx.Graph
    store_path: Path  # JSON 持久化

    def add_note(note_id: str, metadata: dict) -> None
    def add_connection(source: str, target: str, **attrs) -> None
    def get_neighbors(note_id: str, depth: int = 2) -> list[str]
    def find_paths(source: str, target: str) -> list[list[str]]
    def get_subgraph(topic: str) -> nx.Graph
    def save() / def load()
```

### 4.2 接入层 (`brain/ingestion/`)

#### 4.2.1 文件监听器 (`watcher.py`)

```python
class FileWatcher:
    """基于 watchdog 的 Markdown 文件监听"""
    
    def __init__(watched_dir: Path, handler: Callable)
    def start() -> None  # 后台线程
    def stop() -> None
    # 事件: on_created, on_modified, on_deleted
    # 去重: 防抖 (debounce), 文件稳定后才触发
    # 过滤: 只处理 .md 文件, 忽略隐藏文件/目录
```

#### 4.2.2 文档解析器 (`parser.py`)

```python
class DocumentParser:
    """Markdown 解析 + 元数据提取"""
    
    def parse(file_path: Path) -> ParsedDocument:
        # 提取 YAML frontmatter (title, date, tags)
        # 解析 Markdown → 纯文本 (保留结构信息)
        # 计算 file_hash
```

#### 4.2.3 文本分块器 (`chunker.py`)

```python
class SemanticChunker:
    """基于语义边界的自适应分块"""
    
    def chunk(text: str, max_chunk_size: int = 1000, overlap: int = 200) -> list[Chunk]:
        # 优先在段落/标题边界分割
        # 保持每个 chunk 的语义完整性
        # overlap 保证跨 chunk 的上下文连续性
```

### 4.3 流水线层 (`brain/ingestion/pipeline.py`)

这是 LangGraph 的核心应用——摄入流水线状态机：

```python
from langgraph.graph import StateGraph, END
from typing import TypedDict

class IngestionState(TypedDict):
    """摄入流水线状态"""
    source: str                    # 来源文件路径 或 CLI 文本
    raw_content: str               # 原始文本
    parsed_doc: ParsedDocument     # 解析后的文档
    chunks: list[Chunk]            # 文本分块（此节点只做规划，不执行嵌入）
    tags: list[Tag]                # AI 分类标签
    connections: list[Connection]  # 发现的关联
    errors: list[str]              # 每步的错误收集
    current_step: str              # 当前步骤名
    status: str                    # 'running' | 'completed' | 'failed'

def build_ingestion_pipeline() -> StateGraph:
    graph = StateGraph(IngestionState)
    
    graph.add_node("parse", parse_node)         # LangChain 解析
    graph.add_node("chunk", chunk_node)         # 文本分块规划
    graph.add_node("embed", embed_node)         # 嵌入 + 存入 Chroma
    graph.add_node("classify", classify_node)   # DeepAgents 分类
    graph.add_node("connect", connect_node)     # DeepAgents 关联发现
    graph.add_node("index", index_node)         # 写入 PostgreSQL 元数据
    
    # 定义流程
    graph.set_entry_point("parse")
    graph.add_edge("parse", "chunk")
    graph.add_edge("chunk", "embed")
    graph.add_edge("embed", "classify")
    graph.add_edge("classify", "connect")
    graph.add_edge("connect", "index")
    graph.add_edge("index", END)
    
    # 错误处理: 每个节点出错时记录错误到 state.errors，继续执行
    # classify 和 connect 可以并行执行（无依赖关系时）
    
    return graph.compile(checkpointer=PostgresSaver)
```

**错误处理策略**：非关键节点失败不阻塞流水线。解析失败→直接终止；分块失败→终止；嵌入失败→终止；分类失败→跳过，记录错误；关联发现失败→跳过，记录错误。

### 4.4 智能代理层 (`brain/agents/`)

#### 4.4.1 分类 Agent (`classifier.py`)

```python
class ClassifierAgent:
    """DeepAgents — 深度分析笔记内容，生成多维标签"""
    
    # 使用 DeepAgents 的层次化 Agent:
    #   - 子 Agent 1: 识别主题标签 (技术/商业/生活/...)
    #   - 子 Agent 2: 识别内容类型 (教程/观点/摘录/问题/...)
    #   - 子 Agent 3: 识别技术栈 (Python/JavaScript/...)
    #   - 汇总 Agent: 合并子 Agent 结果，去重，赋予置信度
    
    async def classify(note: ParsedDocument) -> list[Tag]
```

#### 4.4.2 关联发现 Agent (`connector.py`)

```python
class ConnectorAgent:
    """DeepAgents — 发现新笔记与已有笔记之间的隐性关联"""
    
    # 策略:
    #   1. 向量相似度粗筛 → Top 20 候选
    #   2. DeepAgents 深度分析 → 判断是否真正相关
    #   3. 确定关系类型: related / extends / contradicts / references
    #   4. 生成关联描述
    
    async def discover_connections(note_id: str) -> list[Connection]
```

#### 4.4.3 摘要合成 Agent (`synthesizer.py`)

```python
class SynthesizerAgent:
    """DeepAgents — 生成每日/每周知识摘要"""
    
    async def daily_digest(date: date) -> Digest
    async def weekly_report(start: date, end: date) -> WeeklyReport
```

#### 4.4.4 深度研究 Agent (`researcher.py`)

```python
class ResearcherAgent:
    """DeepAgents — 多跳推理问答"""
    
    # 流程:
    #   1. 理解问题 → 分解为子问题
    #   2. 对每个子问题执行混合检索
    #   3. 跨笔记推理 → 综合答案
    #   4. 附引用来源
    
    async def research(question: str) -> ResearchResult
```

### 4.5 服务层 (`brain/services/`)

```python
class DigestService:
    """每日摘要服务"""
    async def generate(date: date = today) -> str
    # 收集昨日摄入的笔记 → SynthesizerAgent 生成摘要

class ReviewService:
    """间隔重复服务"""
    async def get_due_items() -> list[Note]
    # 基于 SM-2 算法的复习调度
    async def record_review(note_id: str, quality: int) -> None
```

### 4.6 CLI 层 (`brain/cli/main.py`)

```
Usage: brain [OPTIONS] COMMAND [ARGS]...

Commands:
  add     快速添加一条笔记
  search  语义搜索知识库
  ask     基于知识库的深度问答
  ingest  批量摄入文件/目录
  digest  生成每日/每周知识摘要
  status  查看知识库统计信息
  config  管理配置
  watch   启动文件监听服务（后台运行）
```

### 4.7 API 层 (`brain/api/`)

REST API 后端，FastAPI 实现。**按业务域拆成独立包**，每个包自包含 router + Request/Response 模型，
达到「增改某个业务的接口和数据模型只需动一个包」的粒度。

```
brain/api/
├── __init__.py      # 仅暴露 app
├── app.py           # FastAPI 实例 + lifespan + CORS + 静态文件挂载 + include_router
├── server.py        # 兼容垫片：re-export app（uvicorn brain.api.server:app 不破坏）
├── deps.py          # 服务单例管理：_init() + get_*() 访问器
└── routes/          # 按业务域拆分的独立包（每个包含 router + models）
    ├── notes/          # 笔记：增/摄入/内容/编辑/状态/关联/标签
    │   ├── __init__.py     # re-export router
    │   ├── router.py       # APIRouter 端点
    │   └── models.py       # NoteAddRequest/NoteResponse/NoteEditRequest/...
    ├── search/         # 语义搜索
    │   ├── __init__.py
    │   ├── router.py
    │   └── models.py       # SearchResponse/SearchResultItem
    ├── ask/            # 深度问答 + 会话 + 片段（HIL）
    │   ├── __init__.py
    │   ├── router.py
    │   └── models.py       # AskRequest/AskResponse/ResumeRequest/SessionItem/...
    ├── sources/        # 数据源：文件监听 / RSS / 书签导入
    │   ├── __init__.py
    │   ├── router.py
    │   └── models.py       # WatchStatusResponse/RssAddRequest/BookmarkImportResponse
    ├── scheduler/      # 定时任务 / 摘要报告 / 知识图谱
    │   ├── __init__.py
    │   ├── router.py
    │   └── models.py
    ├── observability/  # 健康检查 / 指标 / 成本
    │   ├── __init__.py
    │   ├── router.py
    │   └── models.py
    ├── eval/           # 评估闭环：feedback/scores/bad-cases/golden-cases/runs
    │   ├── __init__.py
    │   ├── router.py
    │   └── models.py       # EvalFeedbackRequest/GoldenCaseRequest
    ├── prompts/        # 提示词 CRUD + 版本管理
    │   ├── __init__.py
    │   ├── router.py
    │   └── models.py       # PromptUpdateRequest
    └── review/         # SM-2 复习
        ├── __init__.py
        ├── router.py
        └── models.py       # ReviewRecordRequest
```

**设计要点：**
- **业务域自包含**：每个业务一个包，`router.py` 定义端点，`models.py` 定义该域的 Request/Response。
  增删改某业务的接口和数据模型只动一个包，不牵扯其他包
- **依赖集中管理**：`deps.py` 持有 `_pipeline/_vector_store/_metadata_store/_hybrid_searcher/_checkpointer/_scheduler/_watcher` 全局单例，
  `_init()` 懒加载初始化。路由通过 `get_metadata_store()` 等访问器获取，不再每个端点写 `_init()`
- **消除反向依赖**：原 `brain/prompts.py` 反向 import `brain.api.server._metadata_store`，
  拆分后改为 `deps.get_metadata_store()`，业务层不再依赖 API 层
- **兼容垫片**：`server.py` re-export `app`，保证 `uvicorn brain.api.server:app`、`main.py`、
  测试 fixture（`import brain.api.server as server_module`）不破坏

---

## 5. 数据流

### 5.1 摄入流程

```
用户输入 (文件/CLI/RSS/书签)
    │
    ▼
┌──────────────────┐
│ 1. 接收 & 预处理  │  判断来源类型 → 统一解析为 ParsedDocument
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│ 2. 解析          │  Markdown → 纯文本 + frontmatter 元数据
└──────┬───────────┘  (LangChain: UnstructuredMarkdownLoader 或自研)
       │
       ▼
┌──────────────────┐
│ 3. 分块          │  语义分块，保留段落/标题边界
└──────┬───────────┘  (LangChain: 自定义 SemanticChunker)
       │
       ▼
┌──────────────────┐
│ 4. 嵌入 + 向量存储│  BGE-large-zh → pgvector
└──────┬───────────┘  (LangChain: HuggingFaceEmbeddings + Chroma)
       │
       ▼
┌──────────────────┐
│ 5. 分类          │  DeepAgents → 多维标签
└──────┬───────────┘  写入 PostgreSQL note_tags
       │
       ▼
┌──────────────────┐
│ 6. 关联发现      │  DeepAgents → 发现关联 → 写入 PostgreSQL connections
└──────┬───────────┘  同时更新 NetworkX 图
       │
       ▼
┌──────────────────┐
│ 7. 元数据索引    │  写入 PostgreSQL notes 表
└──────┬───────────┘
       │
       ▼
    完成 ✓
```

### 5.2 查询流程

```
用户问题
    │
    ▼
┌──────────────────┐
│ 1. 意图识别      │  搜索型? 问答型? 浏览型?
└──────┬───────────┘  (LangGraph QueryRouter)
       │
       ├─ 搜索型 ──────────┐
       │                    ▼
       │            ┌──────────────┐
       │            │ 混合检索     │  pgvector 向量 + pg_trgm 关键词
       │            │ → 排名 → 返回│
       │            └──────────────┘
       │
       ├─ 问答型 ──────────┐
       │                    ▼
       │            ┌──────────────────┐
       │            │ RAG 流水线       │
       │            │ 检索 → 重排 →    │
       │            │ DeepAgents 推理→ │
       │            │ 合成答案+引用    │
       │            └──────────────────┘
       │
       └─ 浏览型 ──────────┐
                            ▼
                    ┌──────────────┐
                    │ 按标签/时间  │
                    │ 浏览 → 返回  │
                    └──────────────┘
```

---

## 6. 配置设计 (`~/.brain/config.yaml`)

```yaml
# 存储路径
storage:
  data_dir: "~/.brain/data"
  notes_dir: "~/.brain/notes"       # 被监听的 Markdown 文件夹

# 数据库（PostgreSQL）
database:
  host: localhost
  port: 5432
  user: postgres
  password: ""
  database: brain                  # 业务+向量+检查点统一存此库

# LLM 配置
llm:
  provider: "anthropic"
  model: "claude-fable-5"
  api_key: "${ANTHROPIC_API_KEY}"   # 环境变量引用
  max_tokens: 4096
  temperature: 0.3

# Embedding 配置
embedding:
  provider: "local"
  model: "all-MiniLM-L6-v2"
  device: "cpu"                      # cpu | cuda

# 摄入配置
ingestion:
  watch_dir: "~/.brain/notes"        # 监听目录
  chunk_size: 1000                   # 分块大小（字符数）
  chunk_overlap: 200                 # 重叠长度
  debounce_seconds: 2                # 文件防抖时间
  
# Agent 配置
agents:
  classifier:
    enabled: true
    min_confidence: 0.6
  connector:
    enabled: true
    top_k_candidates: 20
    min_strength: 0.5
  synthesizer:
    daily_digest_time: "08:00"      # 每日摘要生成时间

# 数据源配置
sources:
  rss:
    enabled: false
    feeds: []                        # RSS 源列表
    sync_interval_minutes: 60
  bookmarks:
    enabled: false

# 日志
logging:
  level: "INFO"                      # DEBUG | INFO | WARNING | ERROR
  file: "~/.brain/logs/brain.log"
```

---

## 7. 目录结构

```
deep_agents/                        # 项目根目录
├── docs/
│   ├── requirements.md             # 需求文档（每次迭代前更新）
│   └── design.md                   # 项目设计文档（本文件，每次迭代前更新）
├── brain/                          # 主包
│   ├── __init__.py
│   ├── config.py                   # 配置加载 (pydantic-settings)
│   ├── models.py                   # 核心数据模型 (Pydantic)
│   ├── ingestion/
│   │   ├── __init__.py
│   │   ├── watcher.py              # watchdog 文件监听
│   │   ├── parser.py               # Markdown 解析器
│   │   ├── sources/
│   │   │   ├── __init__.py
│   │   │   ├── markdown.py         # Markdown 文件源
│   │   │   ├── cli_input.py        # CLI 直接输入
│   │   │   ├── rss.py              # RSS 源 (P2)
│   │   │   └── bookmark.py         # 书签源 (P2)
│   │   ├── chunker.py              # 语义分块器
│   │   └── pipeline.py             # LangGraph 摄入流水线
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── vector_store.py         # pgvector 封装
│   │   ├── metadata.py             # PostgreSQL 元数据封装
│   │   └── graph_store.py          # NetworkX 图存储 (P2)
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── base.py                 # Agent 基类
│   │   ├── classifier.py           # 分类 Agent (DeepAgents)
│   │   ├── connector.py            # 关联发现 Agent (DeepAgents)
│   │   ├── synthesizer.py          # 摘要合成 Agent (DeepAgents)
│   │   └── researcher.py           # 深度问答 Agent (DeepAgents)
│   ├── retrieval/
│   │   ├── __init__.py
│   │   ├── hybrid_search.py        # 混合检索（向量+关键词）
│   │   └── query_router.py         # LangGraph 查询路由
│   ├── services/
│   │   ├── __init__.py
│   │   ├── digest.py               # 每日摘要服务
│   │   └── review.py               # 间隔重复服务 (P2)
│   └── cli/
│       ├── __init__.py
│       └── main.py                 # Click CLI 入口
├── tests/                          # 测试目录
│   ├── conftest.py                 # pytest fixtures
│   ├── test_ingestion/
│   ├── test_storage/
│   ├── test_agents/
│   └── test_retrieval/
├── data/                           # 开发用测试数据（gitignore）
│   └── sample_notes/
├── CLAUDE.md                       # Claude Code 项目指南
├── .env.example
├── .gitignore
├── pyproject.toml                  # 项目元数据 + ruff 配置
└── README.md
```

---

## 8. 错误处理策略

```
层级          | 策略
-------------|--------------------------------------------------
接入层       | 解析失败 → 记录日志，返回错误，不阻塞后续文件
流水线层     | 非关键节点失败 → 记录 state.errors，继续执行
Agent 层     | LLM 调用失败 → 指数退避重试 3 次 → 降级返回
存储层       | 写入失败 → 抛异常，由上层决定是否重试
CLI 层       | 捕获所有异常 → 友好的错误信息 + 日志路径提示
```

---

## 9. 测试策略

| 层级 | 测试类型 | 覆盖目标 |
|------|----------|----------|
| 存储层 | 单元测试 | PostgreSQL CRUD、pgvector 读写（用独立 schema 隔离） |
| 接入层 | 单元测试 | Markdown 解析、分块逻辑 |
| 流水线 | 集成测试 | 端到端摄入流程（用测试 LLM/Embedding mock） |
| Agent | 单元测试 | Mock LLM 响应，验证 Agent 输出格式 |
| CLI | 集成测试 | Click CliRunner 端到端 |

---

## 10. Phase 1 开发任务清单 ✅

- [x] 项目骨架搭建：`pyproject.toml`、目录结构、`.gitignore`
- [x] 数据模型定义：`brain/models.py`（NoteMetadata, Chunk, Tag, Connection）
- [x] 配置系统：`brain/config.py`（pydantic-settings + 环境变量）
- [x] 存储层：VectorStore + MetadataStore
- [x] 接入层：Markdown 解析器 + 分块器
- [x] LangGraph 摄入流水线：parse → chunk → embed → index
- [x] CLI：`add`、`search`、`ask`、`ingest`、`status` 命令
- [x] 测试：存储层测试、解析器测试
- [x] 文档：README.md 使用指南
- [x] LLM 统一入口：`brain/llm.py`（支持 DeepSeek / Anthropic 切换）
- [x] 数据路径改为项目目录下 `data/`

---

## 11. Phase 2 开发任务清单 ✅（已完成）

- [x] Agent 基类：`brain/agents/base.py` — DeepAgents 配置 + 通用执行器
- [x] 分类 Agent：`brain/agents/classifier.py` — 分析笔记生成多维标签
- [x] 关联 Agent：`brain/agents/connector.py` — 向量粗筛 + DeepAgents 深度分析
- [x] 流水线扩展：`classify` 和 `connect` 节点，执行后写入 PostgreSQL
- [x] CLI 扩展：`search --tag` 按标签过滤、`brain connections` 查看关联
- [x] 测试：Agent 输出格式验证（mock LLM 响应）

### 11.1 Phase 2 核心设计

**分类 Agent 流程：**
```
笔记内容 → get_chat_model()
    │
    ▼
DeepAgents 结构化 Prompt:
  "分析以下笔记，输出 JSON：
   { topics: [{name, confidence}], type: {name, confidence}, difficulty: {name, confidence} }"
    │
    ▼
解析 JSON → Tag 列表 → 写入 PostgreSQL note_tags
```

**关联 Agent 流程：**
```
新笔记 note_id
    │
    ▼
1. pgvector 向量搜索 → Top 20 候选笔记
    │
    ▼
2. DeepAgents 深度分析 Prompt:
   "新笔记: {content} / 候选笔记: {candidates} / 判断是否有意义关联"
    │
    ▼
3. 输出 [{target_note_id, relation_type, strength, description}]
    │
    ▼
4. 写入 PostgreSQL connections
```

**流水线变化：**
```
Phase 1: parse → chunk → embed → index
Phase 2: parse → chunk → embed → classify → connect → index
```
classify 和 connect 在 embed 后串行执行（实际实现中为顺序节点，避免并发写入冲突），都完成后进入 index。

---

## 12. Phase 3 开发任务清单 ✅（已完成）

- [x] DigestService：`brain/services/digest.py` — 每日摘要 + 每周趋势
- [x] ReviewService：`brain/services/review.py` — SM-2 间隔重复复习
- [x] TaskScheduler：`brain/services/scheduler.py` — 后台线程定时任务
- [x] CLI：`brain digest [--weekly]` / `brain review` / `brain watch` / `brain rss`
- [x] Web UI：FastAPI 后端 + Vue3 前端（问答/搜索/图谱/复习/片段/RSS）
- [x] 流式问答：SSE 思考/工具/答案分区输出
- [x] 会话管理 + 三层记忆（工作窗口/向量检索/HIL 知识沉淀）
- [x] 知识图谱可视化（ECharts 力导向图）
- [x] 测试：92 项全绿（存储/API/HIL/性能回归）

### 12.1 Phase 3 核心设计

**每日摘要流程：**
```
brain digest
    │
    ▼
1. 收集昨日摄入的笔记（PostgreSQL）
    │
    ▼
2. 收集昨日的 AI 标签 + AI 关联
    │
    ▼
3. LangChain PromptTemplate 组装上下文
    │
    ▼
4. get_chat_model().invoke() → 结构化摘要
    │
    ▼
5. 终端输出（Markdown 格式）
```

**每周趋势流程：**
```
brain digest --weekly
    │
    ▼
1. 收集本周所有笔记 + 标签分布
    │
    ▼
2. 统计 Top 标签、新增关联数
    │
    ▼
3. LLM 分析："本周你的知识积累呈现什么趋势？"
    │
    ▼
4. 终端输出
```

**复习提醒流程（演进为 SM-2）：**
```
brain review
    │
    ▼
1. 查询 reviews 表到期条目（due_date <= today）
    │
    ▼
2. 不足部分从 notes 表取未进复习系统的笔记（首次候选）
    │
    ▼
3. 卡片流程：回想标题 → 展开内容 → 四档评分
    │
    ▼
4. SM-2 算法更新 ease_factor / interval_days / due_date
```

**HIL（Human-in-the-Loop）中断与消息合并：**

问答中 Agent 若提议保存知识片段（`propose_knowledge` 工具触发 `interrupt_on`），SSE 流会暂停。
用户批准/拒绝后通过 `/api/ask/resume` 恢复。难点是「中断前已流出的答案文本」与「恢复后继续生成的文本」
要合并成**一条** assistant 消息，不能存成两条。

```
ask/stream
  ├─ token...（第一段答案）
  ├─ interrupt → 存入 messages 表（status='pending'），记下 msg_id 到 session.pending_msg_id
  │            timeline 中未完成 tool 标记为 done（中断后不会再收到 tool_end）
  │            流结束，等用户决策
  ▼
ask/resume
  ├─ 从 session.pending_msg_id 取出待续消息
  ├─ token...（第二段答案，累积到同一 answer_parts）
  ├─ done → update_message(msg_id, content=第一段+第二段, timeline=合并, status='complete')
  │         清空 session.pending_msg_id
  └─ 不新增消息
```

关键点：
- 中断时**不新增**独立消息，而是存一条 `status='pending'` 的待续消息，msg_id 暂存到 session 表
- resume 完成时**更新**这条待续消息（追加 content + 合并 timeline），改为 `status='complete'`
- 中断时保存的 timeline 里未收到 tool_end 的 tool，强制标记 `done=True`（恢复后不会重发 tool_end）
- session.pending_msg_id 作为「中断态」标记，同时用于检测「上次中断未恢复」（异常退出后残留）

---

## 13. Phase 4 开发任务清单（当前进行中）

> 详见 [requirements.md §4 Phase 4](./requirements.md#phase-4--需求补全与工程加固当前进行中)。
> 拆为 4A/4B/4C 三个子阶段，遵循"先文档后代码、不引入新框架"约束。

### 13.1 Phase 4A — 文档对齐与质量加固 ✅（已完成）

- [x] FR30 文档同步：requirements/design/CLAUDE.md 对齐 Phase 1-3 已完成状态
- [x] FR31 CLI 性能修复：`brain status`/`connections` 改用 `get_tag_counts`/`get_all_connections_flat`/`get_note_degree_map`，消除 N+1
- [x] FR32 API lifespan 迁移：`@app.on_event("startup")` → `lifespan` 上下文管理器
- [x] FR33 测试提速：`bulk_client` fixture 改 module 级复用，500 条笔记只摄入一次

### 13.2 Phase 4B — P1 功能闭环 ✅（已完成）

- [x] FR34 书签导入：`brain/ingestion/sources/bookmark.py`（解析 Chrome/Firefox JSON），遵循 `SourceProtocol`；CLI `brain bookmarks <path>`；API `POST /api/bookmarks/import`
- [x] FR35 标签浏览：`MetadataStore.list_all_tags()` 新方法；CLI `brain tags`；API `GET /api/tags`；前端标签云页 `Tags.vue`
- [x] FR36 笔记编辑：`MetadataStore.remove_tag_from_note`/`delete_connection`；CLI `brain edit <id>`；API `PATCH /api/notes/{id}`、`DELETE /api/connections/{id}`
- [ ] FR37 多跳推理增强：ResearcherAgent 系统提示词增加显式子问题分解环节（暂缓）

### 13.3 Phase 4C — 实用性增强

- [ ] FR38 数据导出/导入：`brain export` → Markdown 包 + metadata.json；`brain import` 恢复
- [ ] FR39 Embedding 迁移工具：`brain reindex --model <name>` 全量重算向量
- [ ] FR40 主动复习提醒：调度器加超期复习提醒任务，digest 附加待复习条目
- [ ] FR41 测试补齐：书签源/编辑链路/导出导入集成测试

### 13.4 Phase 4 核心设计

#### FR34 书签导入

**设计思路：** 对齐 RSS 源结构——`BookmarkSource` 持有 `pipeline` + `metadata_store`，
解析 JSON 后逐个走完整摄入流水线。不复用 `DocumentParser`（书签无 Markdown 正文，
内容为标题+URL 拼接）。

**Chrome/Firefox JSON 格式差异：**
```python
# Chrome: 根节点 "roots" 下按文件夹嵌套，children 递归
{"roots": {"bookmark_bar": {"children": [{"type":"url","name":"...","url":"..."}, {"type":"folder","children":[...]}]}}}

# Firefox: 平铺数组，带 typeCode (1=folder, 2=bookmark)
{"children": [{"typeCode": 2, "title":"...", "uri":"..."}, {"typeCode": 1, "children":[...]}]}
```

`BookmarkSource.parse(path)` 递归遍历两种格式，统一提取 `(title, url)` 对。

**摄入流程：**
```
brain bookmarks ./bookmarks.json
    │
    ▼
1. BookmarkSource.import_file(path) → 统计 {success, failed, skipped}
    │
    ▼ 逐个书签
2. 构造笔记文本: "# {title}\n\n{url}"
3. file_hash = sha256(url)  ——基于 URL 去重（同一书签重复导入跳过）
4. pipeline.ingest_text_sync(text, title=title)  ——走完整流水线
5. 摄入后补写 source_type=BOOKMARK（覆盖默认的 CLI 类型）
    │
    ▼
3. 返回成功/失败统计
```

**改动点：**
- `brain/ingestion/sources/bookmark.py`：新增 `BookmarkSource` 类
- `brain/ingestion/sources/__init__.py`：导出 `BookmarkSource`
- `brain/ingestion/pipeline.py`：`ingest_text_sync` 增加 `source_type` 参数（默认 CLI，书签传 BOOKMARK）
- `brain/cli/main.py`：新增 `brain bookmarks <path>` 命令
- `brain/api/server.py`：新增 `POST /api/bookmarks/import`（上传文件）

#### FR35 标签浏览

**设计思路：** 复用已有 `get_tag_counts()`（一次 SQL 完成），新增 `list_all_tags()`
补充 category 字段。前端标签云点击跳转 `/search?tag=xxx`（搜索页已有标签过滤）。

**改动点：**
- `brain/storage/metadata.py`：新增 `list_all_tags()` 返回 `[{name, category, count}]`
- `brain/cli/main.py`：新增 `brain tags` 命令（表格输出 [count] tagname）
- `brain/api/server.py`：新增 `GET /api/tags` 返回 `[{name, category, count}]`
- `frontend/src/components/Tags.vue`：标签云页（字号=计数权重，点击跳转搜索）
- `frontend/src/router/index.js`：新增 `/tags` 路由 + 导航项

#### FR36 笔记编辑

**设计思路：** 暴露已有 `update_note`，新增标签增删和关联删除。**内容编辑走重新摄入**
（内容存在 pgvector 分块，原地改内容需重建向量，复杂度高，本期不做）。

**新增存储方法：**
- `MetadataStore.remove_tag_from_note(note_id, tag_name)`：按标签名删除关联（需先查 tag_id）
- `MetadataStore.delete_connection(conn_id)`：按关联 ID 删除

**改动点：**
- `brain/storage/metadata.py`：新增 `remove_tag_from_note`、`delete_connection`
- `brain/cli/main.py`：新增 `brain edit <id> [--title] [--add-tag] [--remove-tag] [--delete-connection]`
- `brain/api/server.py`：新增 `PATCH /api/notes/{id}`（改标题/增删标签）、`DELETE /api/connections/{id}`

**CLI 编辑流程：**
```
brain edit <note_id> --title "新标题" --add-tag python --remove-tag java
    │
    ▼
1. update_note(id, title=...)  ——已存在
2. add_tag_to_note(id, get_or_create_tag(name))  ——已有
3. remove_tag_from_note(id, name)  ——新增
4. delete_connection(conn_id)  ——新增
5. 笔记内容不变（内容编辑走重新摄入流程）
```

#### FR37 多跳推理增强（暂缓）

ResearcherAgent 显式子问题分解环节。当前多次搜索但非显式分解→综合，
本阶段暂不实现（依赖 prompt 调优 + 评估集验证，留待后续迭代）。

---

## 14. Phase 5 开发任务清单（生产化加固，当前进行中）

> 目标：从「能跑」到「可维护」，补足上线后的可观测性、成本治理、容灾、评估能力。
> 面向本地优先单用户场景裁剪生产级要点，不引入 K8s/Redis/Kafka 等重型基础设施。
> 详见 [requirements.md §4 Phase 5](./requirements.md#phase-5--生产化加固当前进行中)。

### 14.1 Phase 5A — 可观测性基础

- [x] FR42 全链路 Trace ID：每次问答生成 trace_id，贯穿 LLM/工具/日志，写入 messages 表
- [x] FR43 结构化 JSON 日志：loguru 增加 JSON sink，带 trace_id/agent/tool 字段
- [x] FR44 核心指标采集：问答延迟/工具调用次数/Token 消耗/摄入耗时写入 metrics 表
- [x] FR45 健康检查：/api/health 探测 LLM/Embedding/PostgreSQL/pgvector 连通性
- [x] FR46 可观测性页面：前端 Observability 页（健康状态/指标看板/最近调用链）

### 14.2 Phase 5A 核心设计

**设计原则：本地优先，轻量实现**
- 不引入 Prometheus/ELK/Jaeger，指标存 PostgreSQL、日志存本地文件、Trace 存 messages 表
- trace_id 用 UUID4 短格式，与现有 note_id 风格一致
- 指标表只追加不修改，符合审计日志原则

**Trace ID 贯穿机制：**
```
用户提问
    │
    ▼
1. /api/ask 或 /api/ask/stream 入口生成 trace_id（UUID4 短格式）
    │
    ▼
2. trace_id 写入 messages 表（timeline 字段补充 trace_id）
    │
    ▼
3. 通过 contextvars 透传到 ResearcherAgent / 工具调用
    │
    ▼
4. 所有日志带 trace_id，便于按会话过滤完整调用链
    │
    ▼
5. 指标记录关联 trace_id，可反查某次问答的全部工具调用
```

**metrics 表设计（核心指标采集）：**
```sql
CREATE TABLE IF NOT EXISTS metrics (
    id SERIAL PRIMARY KEY,
    trace_id TEXT,              -- 关联问答会话
    metric_type TEXT NOT NULL,  -- 'ask'|'ingest'|'tool_call'|'llm_call'
    metric_name TEXT NOT NULL,  -- 'latency_ms'|'token_count'|'count'
    value REAL NOT NULL,
    metadata TEXT,              -- JSON: {model, tool_name, status, ...}
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_metrics_type_time ON metrics(metric_type, created_at);
CREATE INDEX IF NOT EXISTS idx_metrics_trace ON metrics(trace_id);
```

**trace_events 表设计（完整调用链回放）：**
```sql
CREATE TABLE IF NOT EXISTS trace_events (
    id SERIAL PRIMARY KEY,
    trace_id TEXT NOT NULL,
    seq INTEGER NOT NULL,          -- 同一 trace 内递增序号
    event_type TEXT NOT NULL,     -- 'llm_start'|'llm_end'|'tool_start'|'tool_end'
    name TEXT,                     -- 模型名 / 工具名
    input TEXT,                    -- 请求 prompt / 工具入参（截断 2000 字符）
    output TEXT,                   -- 响应文本 / 工具出参（截断 2000 字符）
    token_usage TEXT,             -- JSON: {prompt, completion, total}
    latency_ms REAL,               -- 本步耗时
    run_id TEXT,                   -- LangChain run_id（关联 start/end）
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trace_events_trace ON trace_events(trace_id, seq);
```
metrics 表存数值指标（用于看板聚合统计），trace_events 表存完整入参出参（用于调用链回放）。
两者通过 trace_id 关联，前端展开调用链时同时展示。

**健康检查设计：**
```
GET /api/health
    │
    ▼
返回各组件状态:
{
  "status": "healthy"|"degraded"|"unhealthy",
  "components": {
    "postgres": "ok"|"error",
    "vector": "ok"|"error",
    "embedding": "ok"|"error",
    "llm": "ok"|"skipped"|"error"
  },
  "timestamp": "..."
}
```
LLM/Embedding 探测用最小调用（dry-run 或 1 token），避免消耗配额。

**可观测性页面（前端 Observability.vue）：**
- 健康状态卡片：四组件状态灯（PostgreSQL/pgvector/Embedding/LLM）
- 指标看板：今日问答数、平均延迟、工具调用总数、Token 消耗（折线图/数字卡片）
- 最近调用链：最近 20 条 ask 记录，点击展开看完整调用链回放（LLM 请求响应文本 + 工具入参出参）和数值指标

---

### §14 Phase 5B — 成本治理

#### FR47 Token 实时计费

**设计思路：** 不新建 llm_usage 表，复用 5A 的 trace_events 表——llm_end 事件已记录 token_usage，
只需在 TraceEventLogger.on_llm_end 里增加 cost 字段（按价格表换算）。成本数据天然随 trace_id 关联，
无需额外表。

**内置价格表（¥/1M token，DeepSeek 官方定价 2025-08）：**
```python
MODEL_PRICING = {
    "deepseek-v4-flash": {
        "input": {"idle": {"cache_hit": 0.05, "cache_miss": 1.5},
                 "peak": {"cache_hit": 0.10, "cache_miss": 3.0}},
        "output": {"idle": 4.5, "peak": 9.0},
    },
    "deepseek-v4-pro": {
        "input": {"idle": {"cache_hit": 0.15, "cache_miss": 4.5},
                 "peak": {"cache_hit": 0.30, "cache_miss": 9.0}},
        "output": {"idle": 13.5, "peak": 27.0},
    },
    # 旧型号别名 → v4-flash
    "deepseek-chat": {"_alias": "deepseek-v4-flash"},
}
```
成本计算区分：
- **空闲/高峰时段**：高峰约 2 倍（默认空闲）
- **缓存命中/未命中**：命中价便宜约 30 倍，DeepSeek 返回在 usage_metadata.input_token_details.cache_read
`cost = cache_hit_tokens/1e6 * hit_price + cache_miss_tokens/1e6 * miss_price + completion_tokens/1e6 * output_price`

**改动点：**
- `brain/observability.py`：TraceEventLogger.on_llm_end 增加 cost 计算，写入 token_usage.cost
- `brain/observability.py`：新增 `calc_token_cost(model, prompt, completion)` 工具函数
- trace_events.token_usage JSON 增加 `cost` 字段（单位：¥，保留 6 位小数）

#### FR48 预算配额与熔断

**设计思路：** 两层防护——
1. **预算熔断（软限制）：** 问答入口检查当日/当月累计 token 是否超配额，超限则拒绝新问答（返回 429）
2. **recursion_limit（硬限制）：** ResearcherAgent 的 agent.stream/invoke 传 `recursion_limit`，防止死循环烧 token

**配额配置（config.yaml / 环境变量）：**
```python
class CostSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BRAIN_COST_")
    daily_token_limit: int = 500_000      # 日配额（token）
    monthly_token_limit: int = 5_000_000  # 月配额
    daily_cost_limit: float = 10.0        # 日成本上限（¥）
    recursion_limit: int = 25             # Agent 最大递归步数（防死循环）
```

**熔断检查流程：**
```
/api/ask 或 /api/ask/stream 入口
    │
    ▼
check_budget(metadata_store) → 查今日/本月累计 token
    │
    ├─ 未超限 → 正常执行
    └─ 超限 → 返回 429 + {error: "budget_exceeded", used, limit}
```

**recursion_limit 实现：**
researcher.py 的 agent.stream(config={...}) 增加 `recursion_limit`，超限 LangGraph 抸 RecursionError，
被 server 层捕获转为友好提示。

**改动点：**
- `brain/config.py`：新增 CostSettings
- `brain/observability.py`：新增 `check_budget(ms) -> (ok, used, limit)`
- `brain/api/server.py`：ask/stream/resume 入口加预算检查；recursion_limit 传入
- `brain/agents/researcher.py`：stream/invoke 的 config 增加 recursion_limit

#### FR49 成本报表

**改动点：**
- `brain/storage/metadata.py`：新增 `get_cost_summary(hours)` 聚合查询（总成本/按模型/按日）
- `brain/api/server.py`：新增 `GET /api/cost/summary`、`GET /api/cost/by-model`、`GET /api/cost/daily`
- `brain/cli/main.py`：新增 `brain cost` 命令
- `frontend/src/components/Observability.vue`：看板增加成本卡片（今日成本/月成本/配额进度条）

**数据流：**
```
trace_events.token_usage.cost
    │
    ▼ 聚合
get_cost_summary(hours) → {today_cost, month_cost, daily_limit, used_ratio, by_model, by_day}
    │
    ▼
前端看板：今日 ¥X.XX / 配额进度条 / 按模型成本占比 / 按日趋势
```

---

### §15 Phase 5D — 评估闭环

#### FR53 离线评估测试集

**Golden Dataset 存数据库（golden_cases 表），支持页面 CRUD：**
```sql
CREATE TABLE IF NOT EXISTS golden_cases (
    id TEXT PRIMARY KEY,              -- 如 eval_001
    question TEXT NOT NULL,
    expected_keywords TEXT,           -- JSON 数组
    expected_sources TEXT,            -- JSON 数组（note_id 列表）
    min_score REAL DEFAULT 0.7,
    enabled INTEGER DEFAULT 1,        -- 0=禁用，1=启用
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```
YAML 文件（tests/eval/golden_dataset.yaml）仅作为种子数据，首次启动导入数据库，
之后全部走数据库 + 页面管理。

**评分维度（规则为主，不调 LLM）：**
1. 关键词命中（权重 0.5）：expected_keywords 在回答中出现比例
2. 来源正确性（权重 0.3）：trace_events 里 tool_call 的 note_id 是否命中 expected_sources
3. 完整性（权重 0.2）：回答非空、长度合理（>50 字）

**评分流程：**
```
brain eval [--dataset golden_dataset.yaml] [--limit N]
    │
    ▼ 逐条
ResearcherAgent.research_sync(question, trace_id=eval_xxx)
    │
    ├─ 提取回答文本 → 关键词命中分
    ├─ 查 trace_events 的 tool_call → 来源正确性分
    └─ 回答长度 → 完整性分
    │
    ▼ 加权
score = 0.5*keyword + 0.3*source + 0.2*complete
    │
    ▼
报告：通过率、平均分、失败用例详情
```

**改动点：**
- `brain/storage/metadata.py`：新增 golden_cases 表 + CRUD（add/get/update/delete/toggle）
- `brain/eval/runner.py`：load_dataset 改为从数据库加载
- `brain/api/server.py`：新增 golden cases CRUD 端点
- `brain/cli/main.py`：`brain eval` 从数据库加载；加 `brain eval seed` 从 YAML 导入种子
- `frontend/src/components/EvalCenter.vue`：golden cases 管理（增删改查 + 启用禁用）

#### FR54 Bad Case 回流

**收集触发点：**
1. 用户点踩（Ask.vue 加 👎 按钮）→ POST /api/eval/feedback
2. 问答失败（异常/空回答/recursion_limit 超限）→ server 层自动收集

**bad_cases 存数据库（bad_cases 表），支持页面查看/删除/转 golden：**
```sql
CREATE TABLE IF NOT EXISTS bad_cases (
    id SERIAL PRIMARY KEY,
    trace_id TEXT,
    question TEXT,
    answer TEXT,
    reason TEXT,          -- 'user_thumbs_down'|'empty_answer'|'error'|'recursion_limit'
    extra TEXT,           -- JSON 附加信息
    collected_at TEXT NOT NULL
);
```
收集写入数据库，页面可查看/删除/一键转为 golden case。

**改动点：**
- `brain/storage/metadata.py`：新增 bad_cases 表 + CRUD
- `brain/eval/collector.py`：`collect_bad_case` 改为写数据库
- `brain/api/server.py`：新增 bad cases CRUD 端点 + 一键转 golden
- `frontend/src/components/EvalCenter.vue`：bad cases 管理（查看/删除/转 golden）

#### FR55 LLM-as-Judge 抽样

**Judge prompt 设计：**
输入：问题 + 回答 + 知识库相关片段（从 trace_events 提取）
输出：JSON {score: 1-5, dimensions: {relevance, accuracy, completeness}, comment}

**eval_scores 表：**
```sql
CREATE TABLE IF NOT EXISTS eval_scores (
    id SERIAL PRIMARY KEY,
    trace_id TEXT,
    question TEXT,
    answer TEXT,
    score INTEGER,           -- 1-5
    dimensions TEXT,         -- JSON
    comment TEXT,
    judged_at TEXT NOT NULL
);
```

**改动点：**
- `brain/storage/metadata.py`：新增 eval_scores 表 + CRUD
- `brain/eval/judge.py`：`LLMJudge` 调 DeepSeek 打分
- `brain/services/scheduler.py`：加 weekly_eval 周任务（抽 10%）
- `brain/api/server.py`：新增 GET /api/eval/scores 查趋势

#### 评估历史持久化

**eval_runs 表：记录每次评估批次（离线评估 + Judge 抽样）**
```sql
CREATE TABLE IF NOT EXISTS eval_runs (
    id SERIAL PRIMARY KEY,
    run_type TEXT NOT NULL,     -- 'offline' | 'judge'
    total INTEGER,              -- 用例数 / 抽样数
    passed INTEGER,             -- 通过数（离线评估）
    pass_rate REAL,             -- 通过率
    avg_score REAL,             -- 平均分
    duration_ms REAL,           -- 耗时
    details TEXT,               -- JSON：完整报告摘要（失败用例/各维度均分）
    created_at TEXT NOT NULL
);
```
- 离线评估：`/api/eval/run` 跑完后写入 eval_runs（run_type='offline'）
- Judge 抽样：`/api/eval/judge` 跑完后写入 eval_runs（run_type='judge'）
- `eval_scores` 表加 `run_id` 字段关联 Judge 批次
- API：`GET /api/eval/runs` 查历史，前端总览页显示趋势

---

### §14 Phase 5E — 提示词外部化

#### FR56 提示词外部化（存数据库）

**设计思路：** 提示词是需在线迭代的运营资产——页面编辑、即时生效、版本可追溯。
YAML 文件需重启且无法页面管理，改用 `prompts` 表存储，参照 golden_cases 表的
「配置存库 + 页面 CRUD」先例。

**prompts 表设计：**
```sql
CREATE TABLE IF NOT EXISTS prompts (
    prompt_key TEXT PRIMARY KEY,   -- 'classifier'|'connector'|'researcher'|'title_writer'|'knowledge_extractor'|'judge'
    name TEXT NOT NULL,            -- 中文名
    description TEXT,              -- 用途说明
    content TEXT NOT NULL,         -- 提示词正文（可能含 {占位符}）
    is_template INTEGER DEFAULT 0, -- 是否含 {占位符}（judge 用 .format 渲染）
    enabled INTEGER DEFAULT 1,
    version INTEGER DEFAULT 1,     -- 修改时递增
    updated_at TEXT NOT NULL
);
```

**10 个提示词清单：**
| key | 来源 | 调用方式 |
|-----|------|--------|
| classifier | agents/classifier.py | BaseAgent.system_prompt property |
| connector | agents/connector.py | BaseAgent.system_prompt property |
| researcher | agents/researcher.py 主 Agent | create_deep_agent(system_prompt=) |
| title_writer | researcher.py 子智能体 | SubAgent(system_prompt=) |
| knowledge_extractor | researcher.py 子智能体 | SubAgent(system_prompt=) |
| judge | eval/judge.py | get_prompt_template(question=,answer=,context=) |
| query_rewriter | retrieval/query_rewriter.py | get_prompt_template(query=,count=) |
| daily_digest | services/digest.py | get_prompt_template(notes_section=,...) |
| weekly_trend | services/digest.py | get_prompt_template(notes_section=,...) |
| cli_ask | cli/main.py _ask_simple | get_prompt_template(context=,question=) |

> 所有提示词一律从数据库读取，**代码中不得硬编码**。新增提示词只需在
> `prompt_defaults.py` 的 `DEFAULT_PROMPTS` 加一条，`_seed_prompts` 会自动补充进已初始化的库。

**读取层（新增 brain/prompts.py）：**
- `get_prompt(key) -> str`：从库读 + 进程内字典缓存，避免每次 Agent 调用都查库
- `get_prompt_template(key, **kwargs) -> str`：读取 + `.format()` 渲染（judge 用）
- `reload_prompts()`：清缓存（编辑保存后调用，即时生效）
- 缓存 key 为 prompt_key，upsert 时从缓存字典 pop 掉

**Agent 层改造：**
- `base.py`：`system_prompt` 从类属性改为 `@property`，getter 调 `get_prompt(self.name)`；
  `run()` 改用 `[SystemMessage(system_prompt), HumanMessage(user_prompt+schema)]` 分离角色（原拼字符串全部当 user）
- `classifier.py` / `connector.py`：删 `system_prompt` 类属性，靠基类 property 读
- `researcher.py`：`_build_agent()` 里 3 处 `system_prompt=` 改读 `get_prompt(key)`（DeepAgents 内部已正确构造 SystemMessage）
- `eval/judge.py`：`JUDGE_PROMPT` 改调 `get_prompt_template("judge", ...)`；提示词用 `---USER---` 标记 system/user 边界，运行时拆分为两条消息
- `retrieval/query_rewriter.py`：改调 `get_prompt_template("query_rewriter", query=, count=)`
- `services/digest.py`：删 `DAILY_DIGEST_PROMPT`/`WEEKLY_TREND_PROMPT` 硬编码 `PromptTemplate`，改调 `get_prompt_template("daily_digest"/"weekly_trend", ...)`
- `cli/main.py`：`_ask_simple` 的内联 f-string prompt 改调 `get_prompt_template("cli_ask", context=, question=)`

**初始化与种子：**
- `MetadataStore.initialize()` 后调 `seed_prompts()`
- 幂等：空表写入全部默认值；已有数据时遍历 `DEFAULT_PROMPTS` 补充缺失的 key（增量升级，如旧库新增 query_rewriter/daily_digest/weekly_trend/cli_ask）
- 提示词初始值 = `prompt_defaults.py` 的 `DEFAULT_PROMPTS`（10 条）

#### FR56a 提示词管理页面

- 后台新增「提示词管理」页，复用 golden_cases 的 CRUD 模式
- 列表展示 key/名称/版本/启用状态；点击进入编辑
- 编辑器：大文本框 + 保存按钮；保存后调 `reload_prompts()` 即时生效
- API：GET /api/prompts、GET /api/prompts/{key}、PUT /api/prompts/{key}

---

### §16 Phase 5F — RAG 质量增强

> 目标：把检索从「纯向量召回」升级为「BM25 + 向量 + RRF 融合 + Rerank 精排 + 查询改写」。
> 详见 [requirements.md §4 Phase 5F](./requirements.md#phase-5f--rag-质量增强当前进行中)。

#### 16.1 现状与问题

当前检索链路（`brain/retrieval/` 目录为空，逻辑散落在两处）：

```
researcher.search_notes 工具  ──┐
                               ├─→ VectorStore.search()  (纯向量, cosine)
/api/search (server.py)       ──┘
```

**问题：**
1. 纯向量召回对精确关键词（专有名词、代码标识符、人名）不敏感——语义相近但关键词不命中
2. 无精排，Top-K 直接由向量相似度决定，相似度高 ≠ 最相关
3. 单一查询表达，用户问法多样时召回不全

#### 16.2 目标架构

```
用户查询 query
    │
    ▼
┌─────────────────────────────┐
│ QueryRewriter (FR60, 可选)   │  LLM 生成 3 个改写版本
│  失败/关闭 → 降级为 [query]   │  （多路召回提升语义覆盖）
└──────────┬──────────────────┘
           │ queries: list[str]
           ▼
┌─────────────────────────────────────────────┐
│ HybridSearcher (FR58)                         │
│  对每个 q 并行执行两路召回：                  │
│    ├─ VectorStore.search(q)  → 向量分 (0~1)   │
│    └─ MetadataStore.bm25_search(q) → BM25 分  │
│  RRF 融合 → 去重(note_id 粒度) → Top-N 候选    │
└──────────┬──────────────────────────────────┘
           │ candidates: list[SearchResult]
           ▼
┌─────────────────────────────┐
│ Reranker (FR59, 可选)        │  SiliconFlow /v1/rerank
│  失败/关闭 → 原序返回 Top-K  │  cross-encoder 精排
└──────────┬──────────────────┘
           │ final: list[SearchResult] (Top-K)
           ▼
    返回给 search_notes 工具 / /api/search
```

**降级链（任一环节失败不阻塞）：**
- QueryRewriter 失败 → 用原 query 单路
- BM25 失败 → 仅向量召回
- Reranker 失败/关闭 → 用 RRF 融合后的原序

#### 16.3 FR58 混合检索 + RRF 融合

**BM25 索引设计（双后端）：**

索引对象：笔记标题 + content_preview（PostgreSQL 已有字段，不双写 chunk 全文）。
理由：BM25 价值在精确关键词命中，标题和前 200 字预览已覆盖主要关键词；
chunk 全文只在 pgvector，双写会引入数据一致性问题。

```sql
-- PostgreSQL: pg_trgm GIN 索引（直接挂在 notes 表，写入即同步，支持中文 ILIKE）
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX IF NOT EXISTS idx_notes_title_trgm
    ON notes USING gin (title gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_notes_preview_trgm
    ON notes USING gin (content_preview gin_trgm_ops);

-- 查询：ILIKE 模糊匹配 + similarity() 排序（中文友好，CJK 按 trigram 切分）
SELECT id, title, content_preview,
       similarity(title || ' ' || content_preview, :query) AS score
FROM notes
WHERE status = 'active'
  AND (title ILIKE '%' || :query || '%'
       OR content_preview ILIKE '%' || :query || '%')
ORDER BY score DESC
LIMIT :top_k;
```

统一封装在 `MetadataStore.bm25_search(query, top_k)` 内，调用方无感知后端实现。

**RRF 融合公式：**

对每个候选 chunk c，其在向量结果排名 r_v、BM25 结果排名 r_b（从 1 开始，未出现记 ∞）：

```
RRF_score(c) = Σ  1 / (k + rank_i)    # k=60 (标准常数)
             over {向量, BM25}
```

去重粒度：note_id（同一笔记多 chunk 命中只取最高分 chunk 代表）。
返回 Top-N 候选（默认 30）供 Reranker 精排。

**统一入口 `brain/retrieval/hybrid_search.py`：**
```python
class HybridSearcher:
    def __init__(self, vector_store, metadata_store, reranker=None, rewriter=None):
        ...

    def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        # 1. 查询改写（可选）
        queries = self._rewriter.rewrite(query) if self._rewriter else [query]
        # 2. 多路召回 + RRF 融合
        candidates = self._retrieve_and_fuse(queries, top_n=30)
        # 3. Rerank 精排（可选）
        if self._reranker:
            candidates = self._reranker.rerank(query, candidates, top_k=top_k)
        else:
            candidates = candidates[:top_k]
        return candidates
```

**双调用方改造：**
- `researcher._build_tools()`：`search_notes` 工具内部 `vs.search()` → `hybrid_searcher.search()`
- `server.search_notes()`：`_vector_store.search()` → `_hybrid_searcher.search()`
- `ResearcherAgent.__init__` 注入 `HybridSearcher`（构造时由 server/CLI 组装依赖）

#### 16.4 FR59 Rerank 精排

**SiliconFlow Rerank API：**
```
POST https://api.siliconflow.cn/v1/rerank
{
  "model": "BAAI/bge-reranker-v2-m3",
  "query": "用户原始问题",
  "documents": ["候选1文本", "候选2文本", ...],
  "top_n": 5,
  "return_documents": false
}
→ {"results": [{"index": 0, "relevance_score": 0.98}, ...]}
```
复用现有 `SILICONFLOW_API_KEY` 和 `base_url`，零新依赖。

**`brain/retrieval/reranker.py`：**
```python
class Reranker:
    def __init__(self, api_key, base_url, model="BAAI/bge-reranker-v2-m3"):
        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self._model = model

    def rerank(self, query: str, candidates: list[SearchResult], top_k: int) -> list[SearchResult]:
        documents = [c.content[:500] for c in candidates]  # 截断防超限
        resp = self._client.post("/rerank", ...)
        # 按 relevance_score 降序重排 candidates，取 top_k
        # 失败 → log warning, 原序返回 top_k（降级）
```

**config 开关：**
```python
class RetrievalSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BRAIN_RETRIEVAL_")
    hybrid_enabled: bool = True        # 混合检索总开关
    bm25_weight: float = 0.5          # RRF 中 BM25 路权重（预留，RRF 本身无权重）
    rerank_enabled: bool = True       # Rerank 开关
    rerank_top_n: int = 30            # Rerank 输入候选数
    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    query_rewrite_enabled: bool = True  # 查询改写开关
    query_rewrite_count: int = 3      # 改写版本数
```

#### 16.5 FR60 查询改写（Multi-Query）

**`brain/retrieval/query_rewriter.py`：**
```python
class QueryRewriter:
    def __init__(self, llm, count=3):
        self._llm = llm
        self._count = count

    def rewrite(self, query: str) -> list[str]:
        prompt = "用不同表达方式改写以下搜索查询，生成 {n} 个语义等价但用词不同的版本，"
                "用于提升知识库召回率。每行一个，不要编号。\n\n原查询：{q}"
        resp = self._llm.invoke([HumanMessage(prompt.format(n=self._count, q=query))])
        lines = [l.strip() for l in resp.content.split("\n") if l.strip()]
        return [query] + lines[:self._count]  # 首位保留原查询
```

复用主 LLM（DeepSeek），提示词纳入 5E 的 prompts 表（key=`query_rewriter`），
页面可编辑。失败时降级为 `[query]`。

**多路召回去重：**
多个 query 各自走 HybridSearcher 的向量+BM25 两路，结果按 note_id 去重
（取最高 RRF 分），再进 Reranker。

#### 16.6 依赖组装

`server.py` / `cli/main.py` 初始化时组装检索链路：
```python
reranker = Reranker(...) if config.retrieval.rerank_enabled else None
rewriter = QueryRewriter(get_chat_model(), ...) if config.retrieval.query_rewrite_enabled else None
hybrid_searcher = HybridSearcher(vector_store, metadata_store, reranker, rewriter)
researcher = ResearcherAgent(vector_store, metadata_store, hybrid_searcher)
```

#### 16.7 测试策略

- `tests/test_retrieval/test_hybrid_search.py`：RRF 融合逻辑（mock 两路结果验证排名）、降级路径（BM25 失败仅向量）
- `tests/test_retrieval/test_reranker.py`：mock SiliconFlow API 响应，验证重排 + 失败降级
- `tests/test_retrieval/test_query_rewriter.py`：mock LLM 响应，验证解析 + 失败降级
- `tests/test_storage/test_bm25.py`：pg_trgm 关键词检索（用独立 schema 隔离测试）
- 集成测试：`brain eval` 跑 golden dataset，对比 5F 前后通过率（量化收益）

---

### §17 Phase 5C — 容灾与备份

#### FR51 LLM 调用容灾（引入 tenacity）

**现状问题：**

项目有 6 处 `llm.invoke()` 调用（base/judge/digest/query_rewriter/cli/main/researcher），
仅 `base.py` 手写了重试循环，其余 5 处裸调用，失败即抛异常。
手写循环的缺陷：
1. `except Exception` 全捕获——API key 错误、参数错误等不可恢复错误也重试，浪费配额
2. 无抖动（jitter）——多客户端同时重试易踩踏
3. 无异步支持——`time.sleep` 阻塞事件循环
4. 重复造轮子，每个调用点自己写重试逻辑

**方案：使用 ChatOpenAI/ChatAnthropic 原生 max_retries（不包装 tenacity）**

ChatOpenAI/ChatAnthropic 的 `max_retries` 参数透传给底层 OpenAI/Anthropic SDK，
SDK 自带完善的 HTTP 层重试：自动重试 429/5xx/408/409 + 指数退避 + 随机抖动，
鉴权失败(401)/参数错误(400)不重试。应用层不再重复包装 tenacity，避免三重重试。

```python
# brain/llm.py：初始化时传 max_retries
return ChatOpenAI(
    model=cfg.llm.model,
    ...,
    max_retries=cfg.llm.max_retries,  # SDK 原生重试（默认 3）
)
```

**SDK 原生重试覆盖范围（实测 OpenAI SDK `_should_retry`）：**

| HTTP 状态码 | 重试？ | 理由 |
|------------|--------|------|
| 408 | ✅ | 请求超时 |
| 409 | ✅ | 锁超时 |
| 429 | ✅ | 限流（退避后配额恢复） |
| 5xx | ✅ | 服务端临时故障 |
| 401/403 | ❌ | 鉴权失败，不可恢复 |
| 400 | ❌ | 参数错误，不可恢复 |
| `x-should-retry` 响应头 | 遵从 | 服务端显式控制 |

退避策略由 SDK 内部实现（指数退避 + 抖动），无需应用层配置。

**重试职责（最终方案）：**

| 层级 | 处理什么 | 实现方式 |
|------|---------|---------|
| SDK 原生 | HTTP 瞬时错误（429/5xx/超时） | `max_retries` 透传 |
| with_structured_output | 结构化输出 | function calling 在生成时强制 schema，invoke 直接返回 Pydantic 实例 |

base.py 用 `with_structured_output(method="function_calling")`，LLM 在生成时就遵循 schema，
不存在「解析失败」环节，无需应用层重试。HTTP 错误由 SDK max_retries 重试。

> 演进历程：手写 _parse_json（正则提取）→ PydanticOutputParser（生成后解析）→
> with_structured_output（生成时强制结构化）。后两者用 LangChain 现成能力，
> 最终方案彻底消除了「解析」环节。

**改动点：**
- `brain/llm.py`：`_init_deepseek`/`_init_anthropic` 传 `max_retries=cfg.llm.max_retries`
- `brain/agents/base.py`：用 `with_structured_output` 替换 PydanticOutputParser + 外层重试循环
- 其余调用点（judge/digest/query_rewriter/cli）：直接 `llm.invoke()`，SDK 自动重试
- 无需新增依赖（tenacity 不再使用）

> method 选择：实测 DeepSeek `json_mode` 要求 prompt 含 "json" 字样（多余约束），
> `function_calling` 无此限制且稳定，故选 function_calling。

**配置：**

```python
class LLMSettings(BaseSettings):
    max_retries: int = 3  # SDK 原生重试次数（透传给 OpenAI/Anthropic SDK）
```
