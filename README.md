# 🧠 Brain — 个人知识管家（第二大脑）

本地优先、AI 驱动的个人知识管理系统。把碎片信息变成可检索、可关联、可生长的知识网络。

> 基于 **LangChain + LangGraph + DeepAgents** 三大框架构建

## ✨ 功能全景

| 模块 | 功能 |
|------|------|
| 📥 **多渠道摄入** | Markdown 导入、快速记录、文件监听（自动）、RSS 订阅（自动） |
| 🧠 **智能处理** | LangGraph 流水线：解析→分块→嵌入→AI 分类→AI 关联发现 |
| 🔍 **检索问答** | 语义搜索、标签过滤、DeepAgents 深度问答（SSE 流式） |
| 💬 **会话系统** | 多会话管理、历史持久化、子智能体自动生成标题 |
| 🧬 **三层记忆** | 工作记忆（最近10轮）+ 检索记忆（向量化跨会话）+ 知识沉淀（HIL 确认） |
| 🎴 **间隔重复** | SM-2 算法复习卡片：回想→展开→四档评分→自动调度 |
| 🕸️ **知识图谱** | 交互式力导向图：节点=笔记、边=AI 关联、点击提问 |
| ⏰ **主动服务** | 每日摘要（08:00）、每周趋势（周一）、RSS 自动拉取 |
| 📊 **数据看板** | 统计概览、热门标签、关联列表、定时报告 |

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

编辑 `.env` 填入 API Key：

```ini
# LLM（DeepSeek，OpenAI 兼容协议）
DEEPSEEK_API_KEY=sk-xxx

# Embedding（硅基流动，BGE 中文模型）
SILICONFLOW_API_KEY=sk-xxx
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

### CLI 命令

```powershell
brain add "记录一条想法"              # 快速笔记
brain ingest ./notes/                # 批量导入 Markdown
brain search "RAG 优化"              # 语义搜索
brain ask "我关于 XX 的思考？"        # 深度问答
brain watch                          # 监听目录自动摄入
brain rss add <feed-url>             # 添加 RSS 订阅
brain rss fetch                      # 拉取 RSS 文章
brain review                         # 查看待复习卡片
brain digest [--weekly]              # 生成摘要
brain status                         # 知识库统计
```

## 🏗️ 架构

```
┌─────────────────────────────────────────────────┐
│                  Web UI (Vue3)                    │
│   问答(主) | 搜索 | 图谱 | 复习 | 片段 | RSS      │
└──────────────────┬──────────────────────────────┘
                   │ REST + SSE
┌──────────────────▼──────────────────────────────┐
│               FastAPI (brain/api)                │
│    摄入 | 搜索 | 问答流 | 会话 | 图谱 | 调度      │
└──────┬──────────────┬──────────────┬────────────┘
       │              │              │
┌──────▼─────┐ ┌──────▼──────┐ ┌─────▼──────────┐
│ LangGraph   │ │  DeepAgents │ │  Services      │
│ 摄入流水线   │ │ 主Agent+子  │ │ 摘要/复习/调度  │
│ p→c→e→cls  │ │ 智能体委派   │ │                │
│ →conn→idx  │ │ +HIL中断    │ │                │
└──────┬─────┘ └──────┬──────┘ └─────┬──────────┘
       │              │              │
┌──────▼──────────────▼──────────────▼───────────┐
│                 存储层                           │
│  PostgreSQL + pgvector（笔记/记忆/片段向量 + 元数据/会话）  │
└─────────────────────────────────────────────────┘
```

## 🧬 三层记忆架构

| 层 | 机制 | 存储 | 说明 |
|----|------|------|------|
| 工作记忆 | 最近 10 轮消息进上下文 | `messages` 表 | 会话内短期 |
| 检索记忆 | 消息向量化 + 语义检索 + 同会话加权 | pgvector `vec_conversation_memory` | 跨会话按需取回 |
| 知识沉淀 | 子智能体提取 → HIL 用户确认 → 向量入库 | `knowledge_fragments` + pgvector `vec_fragment_memory` | 长期结构化记忆 |

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
pytest tests/ -v          # 92 个测试：存储/API/HIL/性能回归
ruff check brain/         # Lint
```

- 500 笔记性能回归测试（核心接口 <2s 响应）
- GitHub Actions CI：push 自动跑测试 + lint

## 📁 目录结构

```
deep_agents/
├── brain/                  # Python 主包
│   ├── api/                # FastAPI 后端
│   ├── agents/             # DeepAgents（主 Agent + 子智能体 + 中间件）
│   ├── ingestion/          # 摄入（流水线/监听/RSS/解析/分块）
│   ├── storage/            # PostgreSQL + pgvector
│   ├── services/           # 摘要/复习(SM-2)/调度器
│   ├── cli/                # Click CLI
│   ├── llm.py              # LLM 统一入口（provider 可切换）
│   ├── embedding.py        # Embedding 统一入口
│   ├── config.py           # 配置（pydantic-settings）
│   └── models.py           # 数据模型
├── frontend/               # Vue3 + Vite + ECharts
├── tests/                  # 92 个测试
├── docs/                   # 需求/设计文档（文档驱动开发）
└── CLAUDE.md               # Claude Code 项目指南
```

## 📚 文档驱动开发

本项目采用文档驱动：需求变更先更新 `docs/requirements.md`，架构调整先更新 `docs/design.md`，Phase 结束在 `CLAUDE.md` 记录经验教训。

## License

MIT
