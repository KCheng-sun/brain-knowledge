# 个人知识管家（第二大脑）— 需求文档

> 版本: v0.5.0
> 最后更新: 2024-08-13
> 状态: Phase 1-4B 已完成，Phase 4C/5C 进行中

---

## 1. 项目愿景

构建一个**本地优先、AI 驱动**的个人知识管理系统。它不是一个被动存储笔记的仓库，而是一个**主动服务**的"第二大脑"——自动整理摄入的知识、发现隐性关联、在你需要时主动推送洞察，像一个不知疲倦的知识管家。

一句话：**把碎片信息变成可检索、可关联、可生长的知识网络。**

---

## 2. 目标用户

- **首要用户**：开发者 / 技术人员（自己）
- **扩展用户**：知识工作者（研究员、产品经理、写作者）

---

## 3. 核心用户场景（User Stories）

### 3.1 摄入

| ID | 场景 | 优先级 |
|----|------|--------|
| U1 | 我把 Markdown 笔记放到指定文件夹，系统自动识别并摄入 | P0 |
| U2 | 我用命令行快速记录一条想法：`brain add "刚才想到..."` | P0 |
| U3 | 我导入浏览器书签的 JSON 导出文件，系统解析并摄入 | P1 |
| U4 | 我订阅 RSS 源，系统定时拉取新文章并摄入 | P1 |
| U5 | 我按快捷键呼出捕获窗口，输入内容后自动保存 | P2 |

### 3.2 组织

| ID | 场景 | 优先级 |
|----|------|--------|
| U6 | 系统自动为每条笔记打上多维标签（主题、类型、难度等） | P1 |
| U7 | 系统自动发现两条笔记之间的隐性关联并通知我 | P1 |
| U8 | 我可以手动编辑标签和关联，修正 AI 的错误判断 | P2 |

### 3.3 检索

| ID | 场景 | 优先级 |
|----|------|--------|
| U9 | 我用自然语言搜索："关于 RAG 优化的笔记有哪些？" | P0 |
| U10 | 我按时间范围过滤："上周读了哪些文章？" | P0 |
| U11 | 我按标签浏览："所有标记为 #agent 的笔记" | P1 |
| U12 | 我进行跨笔记的多跳推理问答："我关于 A 的思考，和 B 有什么关系？" | P1 |

### 3.4 主动服务

| ID | 场景 | 优先级 |
|----|------|--------|
| U13 | 每天早上收到一份"昨日知识简报" | P1 |
| U14 | 每周收到一份"本周知识趋势"总结 | P2 |
| U15 | 系统提醒我："有一条 7 天前读的笔记该复习了" | P2 |
| U16 | 系统告诉我："你这个月关注最多的话题是 X" | P2 |

---

## 4. 功能需求（按阶段）

### Phase 1 — 核心 MVP ✅ （已完成）

| FR# | 功能 | 描述 | 状态 |
|-----|------|------|------|
| FR1 | 文件导入 | `brain ingest <path>` 导入 Markdown 文件/目录 | ✅ |
| FR2 | CLI 快速添加 | `brain add <content>` 直接将文本摄入 | ✅ |
| FR3 | 语义搜索 | `brain search <query>` 基于向量相似度检索 | ✅ |
| FR4 | 基础问答 | `brain ask <question>` RAG 检索增强生成，引用来源 | ✅ |
| FR5 | 数据持久化 | PostgreSQL + pgvector 本地持久化（向量+元数据统一存储） | ✅ |

### Phase 2 — 智能处理 ✅（已完成）

| FR# | 功能 | 描述 | 状态 |
|-----|------|------|------|
| FR6 | 自动分类 | 摄入时 DeepAgents 自动生成多维标签（主题/类型），写入 PostgreSQL | ✅ |
| FR7 | 关联发现 | DeepAgents 发现新笔记与旧笔记的隐性关联，记录关联类型和描述 | ✅ |
| FR8 | LangGraph 流水线扩展 | 在 embed 节点后增加 classify → connect 两个节点 | ✅ |
| FR9 | 重复检测 | 摄入时按 file_hash 检测重复，提示用户 | ✅ |
| FR10 | CLI 标签浏览 | `brain search --tag python` 模糊匹配标签过滤 | ✅ |
| — | 关联查看 | `brain connections` 查看笔记之间的 AI 关联图谱 | ✅ |
| — | 状态增强 | `brain status` 显示标签数、关联数、热门标签排行 | ✅ |

### Phase 3 — 主动服务 + Web UI + 会话记忆 ✅（已完成）

| FR# | 功能 | 描述 | 状态 |
|-----|------|------|------|
| FR11 | 每日摘要 | `brain digest` — LLM 基于昨日摄入生成结构化知识简报 | ✅ |
| FR12 | 每周趋势 | `brain digest --weekly` — 本周知识主题分布和趋势分析 | ✅ |
| FR13 | 复习提醒 | `brain review` — SM-2 算法复习卡片调度（演进自简单衰减） | ✅ |
| FR14 | 知识问答增强 | 问答结果中展示相关标签和关联，丰富上下文 | ✅ |
| FR15 | Web UI | FastAPI + Vue3 前后端分离界面，问答为主页 | ✅ |
| FR16 | 流式问答 | SSE 流式输出：思考片段 + 工具调用轨迹 + 答案逐字输出 | ✅ |
| FR17 | 会话管理 | 多会话支持：会话列表、历史消息持久化（PostgreSQL）、可切换/删除 | ✅ |
| FR18 | 多层记忆 | 工作记忆（最近10轮）+ 检索记忆（历史消息向量化按需取回） | ✅ |
| FR19 | 知识沉淀（HIL） | 子智能体提取知识片段 → 用户确认后保存；不静默污染笔记库 | ✅ |
| FR20 | 知识片段闭环 | 前端片段浏览页（查看/删除）；问答搜索同时检索片段 | ✅ |
| FR21 | 文件监听 | `brain watch` 监听目录自动摄入，前端显示监听状态 | ✅ |
| FR22 | RSS 订阅 | 配置 RSS 源，定时拉取文章自动摄入 | ✅ |
| FR23 | 测试补齐 | 存储/API/HIL 链路测试，防回归 | ✅ |
| FR24 | 定时任务调度 | RSS 自动拉取（每60分钟）、每日摘要（08:00）、每周趋势（周一）自动生成并持久化 | ✅ |
| FR25 | 知识图谱可视化 | 笔记-关联交互式图谱：节点大小=关联数，点击高亮邻居，边色=关联类型 | ✅ |
| FR26 | 知识片段向量化 | 片段写入 pgvector `vec_fragment_memory`，search_fragments 改语义检索 | ✅ |
| FR27 | 同会话记忆加权 | 检索记忆时同会话旧消息权重提升，保住超窗口对话连续性 | ✅ |
| FR28 | SM-2 间隔重复 | 复习卡片 + 四档评分（忘记/困难/良好/简单）+ SM-2 算法调度 | ✅ |
| FR29 | 工程化 | GitHub Actions CI、loguru 日志文件持久化、性能回归测试、README 重写 | ✅ |

**Phase 3 实现要点：**
- 新增 `brain/services/` 层：DigestService + ReviewService + TaskScheduler
- 摘要生成：收集昨日笔记→LLM 合成；每周趋势：标签分布统计→LLM 解读
- 复习调度从简单衰减演进为完整 SM-2 算法（ease_factor / interval / due_date）
- 三层记忆 + DeepAgents `interrupt_on` 实现 HIL 知识沉淀

---

### Phase 4 — 需求补全与工程加固（当前进行中）

> 目标：补齐需求文档中标 P1 但未实现的功能（书签导入/标签浏览/笔记编辑），
> 消除 Phase 3 遗留的技术债（N+1 查询/废弃 API），并补强数据可移植性。
> 拆为 4A（文档与质量加固）/ 4B（P1 功能闭环）/ 4C（实用性增强）三个子阶段。

#### Phase 4A — 文档对齐与质量加固 ✅（已完成）

| FR# | 功能 | 描述 | 优先级 |
|-----|------|------|--------|
| FR30 | 文档同步 | requirements/design/CLAUDE.md 对齐 Phase 1-3 已完成状态，清理重复冲突内容 | P0 ✅ |
| FR31 | CLI 性能修复 | `brain status`/`connections` 改用已有批量查询方法，消除 N+1 全表遍历 | P0 ✅ |
| FR32 | API lifespan 迁移 | FastAPI `@app.on_event` 废弃装饰器改 `lifespan` 上下文管理器 | P0 ✅ |
| FR33 | 测试提速 | `bulk_client` fixture 改 module 级复用，500 条笔记只摄入一次（92s→16s） | P1 ✅ |

#### Phase 4B — P1 功能闭环 ✅（已完成）

> 补齐需求文档标 P1 但未实现的功能：书签导入、标签浏览、笔记编辑。
> 全部基于现有架构扩展，不引入新框架。

| FR# | 功能 | 描述 | 优先级 | 状态 |
|-----|------|------|--------|------|
| FR34 | 书签导入 | 解析 Chrome/Firefox 书签 JSON 导出，作为 `bookmark` 类型笔记摄入；CLI `brain bookmarks <path>` + API `/api/bookmarks/import` | P1 | ✅ |
| FR35 | 标签浏览 | CLI `brain tags` 列出标签计数排行；API `/api/tags`；前端标签云浏览页 | P1 | ✅ |
| FR36 | 笔记编辑 | 暴露已有 `update_note`：CLI `brain edit <id>`；API `PATCH /api/notes/{id}`；新增编辑标签/删除关联 | P2 | ✅ |
| FR37 | 多跳推理增强 | ResearcherAgent 显式子问题分解环节（现多次搜索但非显式分解→综合） | P2 | ⏸ |

#### Phase 4C — 实用性增强

| FR# | 功能 | 描述 | 优先级 |
|-----|------|------|--------|
| FR38 | 数据导出/导入 | `brain export` 导出全部笔记为 Markdown 包；`brain import` 恢复，满足本地优先可移植性 | P2 |
| FR39 | Embedding 迁移工具 | `brain reindex --model <name>` 全量重算向量，支持换模型不丢数据 | P2 |
| FR40 | 主动复习提醒 | 调度器加超期复习提醒任务，每日摘要附加待复习条目 | P2 |
| FR41 | 测试补齐 | 书签源/编辑链路/导出导入的集成测试 | P1 |

**Phase 4 设计约束：**
- 不引入新框架，全部基于现有 LangGraph + DeepAgents + PostgreSQL + pgvector 扩展
- 书签源遵循 `SourceProtocol`，与 RSS 源结构对齐
- 数据导出格式以 Markdown 为主，附带 metadata.json 保留标签/关联，便于跨实例迁移

---

### Phase 5 — 生产化加固（当前进行中）

> 目标：从「能跑」到「可维护」。补足上线后的可观测性、成本治理、容灾、评估能力。
> 面向本地优先单用户场景裁剪生产级 Agent 要点，不引入 K8s/Redis/Kafka 等重型基础设施。
> 拆为 5A（可观测性）/ 5B（成本治理）/ 5C（容灾备份）/ 5D（评估闭环）/ 5E（提示词外部化）/ 5F（RAG 增强）。

#### Phase 5A — 可观测性基础

| FR# | 功能 | 描述 | 优先级 |
|-----|------|------|--------|
| FR42 | 全链路 Trace ID | 每次问答生成 trace_id，贯穿 LLM/工具调用/日志，写入 messages 表 | P0 ✅ |
| FR43 | 结构化 JSON 日志 | loguru 增加 JSON sink，带 trace_id/agent/tool 字段，便于过滤检索 | P0 ✅ |
| FR44 | 核心指标采集 | 问答延迟/工具调用次数/Token 消耗/摄入耗时写入 metrics 表；CLI `brain metrics` | P0 ✅ |
| FR45 | 健康检查 | `/api/health` 探测 LLM/Embedding/PostgreSQL/pgvector 连通性 | P0 ✅ |
| FR46 | 可观测性页面 | 前端 Observability 页：健康状态灯 + 指标看板 + 最近调用链 | P0 ✅ |

#### Phase 5B — 成本治理 ✅（已完成）

> 衔接 5A：5A 的 trace_events 已记录每次 LLM 调用的 token_usage（prompt/completion/total），
> 5B 在此基础上加价格表换算成本 + 配额熔断 + 成本报表，是最低成本增量。

| FR# | 功能 | 描述 | 优先级 | 状态 |
|-----|------|------|--------|------|
| FR47 | Token 实时计费 | 内置模型价格表（¥/1M token），trace_events 的 llm_end 事件同时记录成本；CLI/API 可查 | P1 | ✅ |
| FR48 | 预算配额与熔断 | 日/月 Token 配额（config 可配，默认日 50万/月 500万）；超限拒绝新问答；ResearcherAgent 加 recursion_limit 硬上限防死循环 | P1 | ✅ |
| FR49 | 成本报表 | `brain cost` 按模型/会话/日期统计；API `/api/cost`；前端 Observability 页加成本看板 | P1 | ✅ |

#### Phase 5C — 容灾与备份

| FR# | 功能 | 描述 | 优先级 |
|-----|------|------|--------|
| FR50 | 数据备份/恢复 | `brain backup` 用 pg_dump 导出 PostgreSQL 全库到压缩包；`brain restore` 恢复 | P1 | ⏸ |
| FR51 | LLM 调用容灾 | 使用 ChatOpenAI/ChatAnthropic 原生 `max_retries` 重试策略（透传给底层 SDK，自动处理 429/5xx/超时 + 指数退避抖动）；`brain/llm.py` 初始化时传入；base.py 保留外层重试仅处理 JSON 解析失败 | P2 | ✅ |
| FR52 | 记忆/片段清理 | 知识片段和会话历史 TTL 清理（调度器加任务） | P2 | ⏸ |

#### Phase 5D — 评估闭环 ✅（已完成）

> 为非确定性 LLM 输出装上「回归测试」：改 prompt/换模型后能量化质量变化，
> bad case 持续沉淀成测试集，LLM-as-Judge 提供主观质量趋势。
> 本地优先：测试集存 YAML，评分用规则+LLM，不引入重框架。

| FR# | 功能 | 描述 | 优先级 | 状态 |
|-----|------|------|--------|------|
| FR53 | 离线评估测试集 | Golden Dataset 存 YAML；`brain eval` 批量问答打分（关键词命中+来源正确性+完整性）；报告总体通过率/失败详情；CI 可接入 | P1 | ✅ |
| FR54 | Bad Case 回流 | 问答页加点踩按钮；点踩/失败/空回答自动收集到 bad_cases.yaml（带 trace_id）；定期人工 review 转为 golden 用例 | P2 | ✅ |
| FR55 | LLM-as-Judge 抽样 | scheduler 周任务抽 10% 问答；DeepSeek 当 Judge 打 1-5 分+评语；写入 eval_scores 表；看板查平均分趋势 | P2 | ✅ |

**Phase 5D 设计约束：**
- 测试集可版本管理（YAML 存 git），不依赖数据库
- 评分以规则为主（关键词/来源/完整性），LLM-as-Judge 为辅（成本可控）
- bad case 收集不影响主流程（异步、失败静默）
- 评估脚本可独立运行（`brain eval`），也可接入 pytest

#### Phase 5E — 提示词外部化

> **调整（2024-08-13）：提示词存数据库而非 YAML 文件。**
> 理由：提示词是需在线迭代的运营资产（页面编辑、即时生效、版本可追溯），
> YAML 文件需重启且无法页面管理。参照 golden_cases 表的「配置存库 + 页面 CRUD」先例。

| FR# | 功能 | 描述 | 优先级 | 状态 |
|-----|------|------|--------|------|
| FR56 | 提示词外部化 | 6 个 system_prompt（classifier/connector/researcher/title-writer/knowledge-extractor/judge）存 `prompts` 表；运行时从库读 + 内存缓存；`brain/prompts.py` 统一读取入口 | P1 | ✅ |
| FR57 | 配置集中化 | 模型路由、Agent 参数、工具注册集中到 config | P2 | ⏸ |
| FR56a | 提示词管理页面 | 后台新增「提示词管理」页：列表/编辑/保存/版本号；编辑后刷新缓存即时生效 | P1 | ✅ |

**Phase 5E 实现要点：**
- `prompts` 表：`prompt_key`(PK) / `name` / `description` / `content` / `is_template`(含 `{占位符}`) / `enabled` / `version` / `updated_at`
- 初始化时 `seed_prompts()` 幂等写入 6 条默认值（迁移现有硬编码内容）
- `get_prompt(key)` 带进程内字典缓存，`upsert_prompt` 时清缓存
- judge 提示词含 `{question}/{answer}/{context}` 占位符，用 `is_template=1` 标记，走 `get_prompt_template(key, **kw)` 渲染
- 其余 5 个提示词为纯文本（`is_template=0`），直接读取使用

#### Phase 5F — RAG 质量增强 ✅（已完成）

> 衔接 5A-5E：可观测性/成本/评估/提示词已就绪，本阶段把检索从「纯向量召回」
> 升级为「BM25 + 向量 + RRF 融合 + Rerank 精排 + 查询改写」的工业级 RAG。
> 优化效果可直接在 Observability 看板和 `brain eval` 评估集上量化对比。
> **设计约束（基于代码实测）：**
> - Chunk 全文只存 pgvector，PostgreSQL 仅有 `content_preview`(200 字)。BM25 索引笔记标题+预览，
>   不双写 chunk 全文（BM25 价值在精确关键词命中，标题/预览已覆盖主要关键词）
> - PostgreSQL 用 pg_trgm GIN 索引 + ILIKE + similarity() 排序，中文友好
> - Rerank 走 SiliconFlow `/v1/rerank` API（`BAAI/bge-reranker-v2-m3`），复用现有 API Key，
>   不引入本地 GB 级 cross-encoder 模型（与轻量原则一致）
> - 查询改写复用主 LLM（DeepSeek），不引入新模型

| FR# | 功能 | 描述 | 优先级 | 状态 |
|-----|------|------|--------|------|
| FR58 | 混合检索 | BM25（pg_trgm GIN 索引笔记标题+预览）+ 向量召回 + RRF 融合；`brain/retrieval/hybrid_search.py` 统一入口；`search_notes` 工具与 `/api/search` 切换调用 | P1 | ✅ |
| FR59 | Rerank 精排 | SiliconFlow `/v1/rerank`（bge-reranker-v2-m3）对融合后 Top-N 精排；`brain/retrieval/reranker.py`；config 开关 + top_n 可配 | P2 | ✅ |
| FR60 | 查询改写 | Multi-Query：LLM 生成 3 个改写版本，多路召回去重后融合，提升语义召回；`brain/retrieval/query_rewriter.py` | P2 | ✅ |

**Phase 5F 设计约束：**
- 本地优先：BM25 索引用 PostgreSQL pg_trgm，Rerank 走已有 SiliconFlow API，不引入新基础设施
- 向后兼容：混合检索失败时降级为纯向量召回（现有 `VectorStore.search`），不阻塞主流程
- 可量化：5A 的 trace_events 已记录每次检索的 tool_call，5F 上线后跑 `brain eval` 对比通过率变化
- 双调用方统一：`server.search_notes`(API) 和 `researcher.search_notes`(工具) 都切到 `HybridSearcher`

**Phase 5 设计约束：**
- 本地优先：指标存 PostgreSQL、日志存本地文件、Trace 存 messages 表，不引入外部时序库
- 轻量：健康检查用最小调用（dry-run 或 1 token）避免消耗配额
- 可观测性是基础：5A 优先做，后续 5B 成本数据天然依赖 trace_id 和指标采集

### Phase 5G — Langfuse 追踪集成

> 将 LLM 调用链接入 Langfuse（本地自托管 v4），获得富 trace 树、会话视图、看板与评分能力，补充 5A 的本地 metrics/trace_events。

| 编号 | 功能 | 说明 | 优先级 | 状态 |
|------|------|------|--------|------|
| FR61 | Langfuse SDK 集成 | 安装 `langfuse` v4 SDK；`brain/langfuse_tracing.py` 统一入口；`.env` 配置 `LANGFUSE_*` 凭证 + `BRAIN_LANGFUSE__*` 开关；无凭证/禁用时降级为空操作，主流程零影响 | P1 | ✅ |
| FR62 | 全链路追踪 | 所有 LLM 调用点接入：ResearcherAgent（stream/resume/invoke）、BaseAgent（classifier/connector）、digest、query_rewriter、judge；trace_name/session_id/tags 遵循最佳实践 | P1 | ✅ |
| FR63 | 双模式适配 | agent/chain 路径用 metadata 模式（`attach_langfuse`），直接 LLM 调用用上下文管理器模式（`langfuse_trace`）；后者用 start_as_current_observation + propagate_attributes 建 trace root | P1 | ✅ |
| FR64 | trace_id 关联 | 应用侧 trace_id 存入 Langfuse metadata.brain_trace_id，与本地 metrics/trace_events 双向互查 | P2 | ✅ |
| FR65 | 生命周期管理 | CLI 入口和 FastAPI lifespan 在退出时 flush/shutdown Langfuse 客户端，确保短进程的 trace 不丢失 | P1 | ✅ |
| FR66 | 提示词接入 Langfuse | 10 个提示词迁移到 Langfuse Prompt Management（label=production）；`brain.prompts` 优先从 Langfuse 读（`get_prompt`/`get_prompt_template` 用 `compile` 渲染 `{{var}}`），回退本地 prompts 表 + prompt_defaults；迁移脚本 `brain.scripts.migrate_prompts_to_langfuse` | P1 | ✅ |

**Phase 5G 设计约束：**
- 本地优先：Langfuse 用本地自托管 v4（docker-compose），不依赖云服务
- 与 5A 并存：Langfuse 提供富 trace 树（generation/tool/span 嵌套），本地 TraceEventLogger 写 metrics 表，两者互补不替代
- 降级安全：无凭证/禁用/SDK 未安装/上下文创建失败，均静默降级，不影响主流程（与 record_metric 一致）
- 遵循最佳实践：trace_name 动词式、session_id 分组多轮对话、environment 隔离 dev/prod 看板、avoid 模型名作 trace_name

---

## 5. 非功能需求

| NFR# | 类别 | 要求 |
|------|------|------|
| NFR1 | 隐私 | **所有数据本地存储**，不上传任何内容到云端（除 LLM API 调用外） |
| NFR2 | 性能 | 单条笔记摄入 < 5s；搜索响应 < 2s；问答响应 < 15s |
| NFR3 | 可扩展 | 数据源和 Agent 可插拔，新增数据源无需修改核心流水线 |
| NFR4 | 容错 | 文件解析失败不阻塞流水线；LLM 调用失败有重试机制 |
| NFR5 | 可观测 | 每次摄入/搜索/问答记录日志；支持 `--verbose` 查看详细过程 |

---

## 6. 数据源定义

| 数据源 | 接入方式 | 内容类型 | Phase |
|--------|----------|----------|-------|
| Markdown 文件 | 文件系统监听（watchdog） | 笔记、文章、想法 | P0 |
| CLI 直接输入 | 命令行参数 / 管道 | 快速笔记 | P0 |
| 浏览器书签 | JSON 文件导入 | 网页书签 | P1 |
| RSS/Atom Feed | 定时拉取（feedparser） | 博客文章、新闻 | P1 |
| 剪贴板 | 热键捕获（pyperclip） | 临时摘录 | P2 |
| Notion API | API 同步 | 数据库页面 | 远期 |

---

## 7. 交互方式

| 方式 | 命令 | Phase |
|------|------|-------|
| CLI | `brain add/search/ask/digest/review/watch/rss/status/connections` | P0 |
| Web UI | `brain ui` 启动 FastAPI + Vue3 本地界面（问答为主页） | ✅ 已实现 |
| 配置文件 | 项目根目录 `.env`（API Key）+ `config.py` 默认值 | P0 |

---

## 8. 成功指标

1. 自己每天使用至少 1 次
2. 能在 3 秒内找到任何历史笔记
3. 每周至少发现 1 条有意义的自动关联
4. 笔记总量增长到 500+ 条时系统仍保持响应速度

---

## 9. 术语表

| 术语 | 定义 |
|------|------|
| **笔记（Note）** | 一条独立的知识单元，可以是一篇文章、一个想法、一段摘录 |
| **摄入（Ingest）** | 将外部内容解析、分块、嵌入、索引进入系统的完整过程 |
| **关联（Connection）** | 两条笔记之间存在有意义的语义关系 |
| **标签（Tag）** | AI 自动生成的多维分类标记 |
| **知识图谱（Knowledge Graph）** | 以笔记为节点、关联为边的图结构 |
| **摘要（Digest）** | 系统主动生成的某段时间内的知识动态报告 |
