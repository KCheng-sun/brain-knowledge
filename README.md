# 🧠 Brain — 个人知识管家（第二大脑）

本地优先、AI 驱动的个人知识管理系统。把碎片信息变成可检索、可关联、可生长的知识网络。

> 基于 **LangChain + LangGraph + DeepAgents** 三大框架构建

## ✨ 功能全景

| 模块 | 功能 |
|------|------|
| 📥 **多渠道摄入** | Markdown 导入、快速记录、文件监听（自动）、RSS 订阅（自动）、浏览器书签导入 |
| 🧠 **智能处理** | LangGraph 流水线：解析→分块→嵌入→AI 分类→AI 关联发现 |
| 🔍 **混合检索** | 向量语义检索 + BM25 关键词检索（pg_trgm）+ Rerank 重排 + 查询改写 |
| 💬 **检索问答** | DeepAgents 深度问答（SSE 流式）、标签过滤、多会话管理、子智能体自动生成标题 |
| 🧬 **三层记忆** | 工作记忆（最近 10 轮）+ 检索记忆（向量化跨会话）+ 知识沉淀（HIL 确认） |
| 🎴 **间隔重复** | SM-2 算法复习卡片：回想→展开→四档评分→自动调度 |
| 🕸️ **知识图谱** | 交互式力导向图：节点=笔记、边=AI 关联、点击提问 |
| ⏰ **主动服务** | 每日摘要（08:00）、每周趋势（周一）、RSS 自动拉取、每周评估抽样 |
| 📊 **数据看板** | 统计概览、热门标签（字号云）、关联列表、定时报告 |
| 🩺 **可观测性** | trace_id 全链路追踪 + JSON 日志 + metrics/trace_events 表 + 健康检查 + 监控页面 |
| 💰 **成本治理** | Token 计费（含缓存命中/空闲高峰）+ 预算熔断（429）+ 成本报表 + usage_counters 表 |
| 🧪 **评估闭环** | Golden Dataset + Bad Case 回流 + LLM-as-Judge + 评估中心页面 |
| 📝 **提示词管理** | prompts 表 + 页面 CRUD + 版本控制 + 即时生效（进程内缓存） |
| ✏️ **笔记编辑** | 标题/标签/关联编辑（内容编辑走重新摄入）+ 书签去重（file_hash） |

## 🚀 快速开始

### 环境准备

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
pip install -r requirements-dev.txt   # 开发依赖（测试/lint）
```

### 配置

```powershell
copy .env.example .env
```

编辑 `.env` 填入 API Key 与 PostgreSQL 连接：

```ini
# LLM（DeepSeek，OpenAI 兼容协议）
DEEPSEEK_API_KEY=sk-xxx

# Embedding / Rerank（硅基流动，BGE 中文模型 + cross-encoder）
SILICONFLOW_API_KEY=sk-xxx

# PostgreSQL（业务数据 + 向量 + Checkpoint 统一存储）
BRAIN_DB_HOST=localhost
BRAIN_DB_PORT=5432
BRAIN_DB_NAME=brain
BRAIN_DB_USER=postgres
BRAIN_DB_PASSWORD=xxx
```

### 启动 Web UI

```powershell
# 后端（FastAPI）
brain ui                    # → http://127.0.0.1:7860

# 前端（Vue3 + Vite，另开终端）
cd frontend
npm install
npm run dev                 # → http://localhost:5173
```

前端路由（Vue Router）：

| 路由 | 页面 |
|------|------|
| `/ask/:sessionId?` | 深度问答（默认首页） |
| `/add` `/import` | 快速记录 / 导入文件 |
| `/search` `/tags` | 语义搜索 / 标签浏览 |
| `/fragments` `/graph` | 知识片段 / 知识图谱 |
| `/review` `/rss` `/dashboard` | 间隔复习 / RSS 订阅 / 知识概览 |
| `/admin/observability` `/admin/eval` `/admin/prompts` | 系统监控 / 评估中心 / 提示词管理 |

### CLI 命令

```powershell
# 摄入与编辑
brain add "记录一条想法"              # 快速笔记
brain ingest ./notes/                # 批量导入 Markdown
brain bookmarks ./bookmarks.json     # 导入浏览器书签
brain watch                          # 监听目录自动摄入
brain edit <note_id> --add-tag xx    # 编辑标题/标签/关联
brain tags                           # 列出全部标签及计数

# 检索与问答
brain search "RAG 优化"              # 混合检索（向量+BM25+Rerank）
brain ask "我关于 XX 的思考？"        # 深度问答（DeepAgents）
brain status                         # 知识库统计
brain connections <note_id>          # 查看 AI 关联

# 摘要与复习
brain digest [--weekly]              # 生成摘要 / 每周趋势
brain review                         # 待复习卡片（SM-2）

# RSS 订阅
brain rss add <feed-url>             # 添加订阅
brain rss list                       # 列出订阅源
brain rss fetch                      # 拉取文章
brain rss remove <feed_id>           # 移除订阅

# 可观测性与成本治理（Phase 5）
brain metrics --hours 24             # 可观测性指标（5A）
brain cost --days 7                  # LLM 调用成本报表（5B）
brain budget [--reset]               # 查看/重置预算用量
brain eval --dataset golden          # 跑离线评估测试集（5D）
```

## 🏗️ 架构

```
┌─────────────────────────────────────────────────────────────┐
│                      Web UI (Vue3 + Router)                  │
│  问答 | 搜索 | 图谱 | 复习 | 片段 | RSS | 看板 | 监控/评估/提示词 │
└──────────────────────────┬──────────────────────────────────┘
                           │ REST + SSE
┌──────────────────────────▼──────────────────────────────────┐
│               FastAPI (brain/api，按业务域拆包)                │
│  routes/{notes,search,ask,sources,scheduler,                  │
│          observability,eval,prompts,review}                   │
└──────┬──────────────┬──────────────┬────────────┬───────────┘
       │              │              │            │
┌──────▼─────┐ ┌──────▼──────┐ ┌─────▼──────┐ ┌──▼──────────┐
│ LangGraph   │ │  DeepAgents │ │ HybridSrch │ │ Services    │
│ 摄入流水线   │ │ 主Agent+子  │ │ BM25+Rerank│ │ 摘要/复习/   │
│ p→c→e→cls  │ │ 智能体委派   │ │ +查询改写   │ │ 调度/评估    │
│ →conn→idx  │ │ +HIL中断    │ │            │ │             │
└──────┬─────┘ └──────┬──────┘ └─────┬──────┘ └──┬──────────┘
       │              │              │            │
┌──────▼──────────────▼──────────────▼────────────▼───────────┐
│                       存储层                                   │
│  PostgreSQL + pgvector（业务/会话 + 向量 + Checkpoint 统一库）  │
│  ─ notes/sessions/messages/…        业务元数据（19 表）        │
│  ─ vec_note_chunks/vec_conversation_…/vec_fragment_…  向量(3 表) │
│  ─ checkpoint_*                     LangGraph Checkpoint(4 表) │
│  ─ metrics/trace_events/usage_…     可观测性+成本(5 表)        │
└──────────────────────────────────────────────────────────────┘
```

## 🧬 三层记忆架构

| 层 | 机制 | 存储 | 说明 |
|----|------|------|------|
| 工作记忆 | 最近 10 轮消息进上下文 | `messages` 表 | 会话内短期 |
| 检索记忆 | 消息向量化 + 语义检索 + 同会话加权 | pgvector `vec_conversation_memory` | 跨会话按需取回 |
| 知识沉淀 | 子智能体提取 → HIL 用户确认 → 向量入库 | `knowledge_fragments` + pgvector `vec_fragment_memory` | 长期结构化记忆 |

> 中断与恢复的答案会合并成同一条消息（`status='pending'`→`'complete'`），HIL 多 proposal 逐一审批，记忆向量写入用全文（thought + 最后 content）保证语义完整。

## 🔍 混合检索（RAG 增强）

```
用户查询
  │
  ▼
QueryRewriter（LLM 查询改写）
  │
  ├─ 向量检索（pgvector，BGE 语义召回）
  └─ BM25 检索（pg_trgm GIN 索引，关键词精确命中）
        │
        ▼
      RRF 融合（按排名融合，非绝对分）
        │
        ▼
      Rerank（SiliconFlow cross-encoder 重排）
        │
        ▼
      Top-K 结果
```

- **BM25 用 pg_trgm 替代 FTS5**：trigram 按 3 字符切分对 CJK 友好，FTS 结果为空时 LIKE 兜底保证中文召回
- **Rerank 走 API 不下本地模型**：复用 SiliconFlow API，零新依赖、无 GB 级下载

## 🎴 SM-2 间隔重复

```
回想卡片标题 → 展开答案验证 → 四档评分
  😵 忘记(1)  → 间隔重置 1 天
  😅 困难(3)  → 间隔 × 熟练度
  🙂 良好(4)  → 间隔 × 熟练度
  🤩 简单(5)  → 间隔 × 熟练度 + 熟练度提升
复习路径: 1天 → 6天 → 15天 → 37天 → ...
```

## 🧪 测试与质量

```powershell
pytest tests/ -v          # 238 个测试：存储/API/HIL/检索/评估/可观测性/性能回归
ruff check brain/         # Lint
```

测试镜像源码目录结构（`tests/test_storage/test_vector_store.py` 等），PostgreSQL 测试用独立 `test_<uuid>` schema 隔离，测完 DROP CASCADE。

- 500 笔记性能回归测试（核心接口 <2s 响应）
- GitHub Actions CI：push 自动跑测试 + lint

## 📁 目录结构

```
brain-knowledge/
├── brain/                  # Python 主包
│   ├── api/                # FastAPI 后端（routes/ 按业务域拆包 + deps.py 单例）
│   ├── agents/             # DeepAgents（主 Agent + 子智能体 + 中间件）
│   ├── ingestion/          # 摄入（流水线/监听/RSS/解析/分块/书签）
│   ├── retrieval/          # 混合检索（BM25 + Rerank + 查询改写）
│   ├── storage/            # PostgreSQL + pgvector
│   ├── services/           # 摘要/复习(SM-2)/调度器
│   ├── eval/               # 评估闭环（Golden Dataset + Bad Case + Judge）
│   ├── observability.py    # 可观测性（trace/metrics/健康检查）
│   ├── prompts.py          # 提示词读取层（DB + 进程内缓存）
│   ├── cli/                # Click CLI（18 个命令）
│   ├── llm.py              # LLM 统一入口（provider 可切换）
│   ├── embedding.py        # Embedding 统一入口
│   ├── config.py           # 配置（pydantic-settings）
│   └── models.py           # 数据模型
├── frontend/               # Vue3 + Vite + Vue Router + ECharts
├── tests/                  # 238 个测试
├── docs/                   # 需求/设计文档（文档驱动开发）
└── CLAUDE.md               # Claude Code 项目指南
```

## 📚 文档驱动开发

本项目采用文档驱动：需求变更先更新 `docs/requirements.md`，架构调整先更新 `docs/design.md`，Phase 结束在 `CLAUDE.md` 记录经验教训。

## License

MIT
