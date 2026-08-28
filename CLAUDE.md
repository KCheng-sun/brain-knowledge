# CLAUDE.md — 个人知识管家（第二大脑）

> 最后更新: 2024-08-13

---

## 项目概述

**Brain（个人知识管家）** 是一个本地优先、AI 驱动的个人知识管理系统。
核心目标：把碎片信息变成可检索、可关联、可生长的知识网络。

- **项目根目录**: `D:\projects\brain-knowledge`
- **主包名**: `brain`
- **Python 版本**: 3.13+
- **平台**: Windows 11 (PowerShell 5.1)
- **数据库**: PostgreSQL 17 + pgvector（业务数据 + 向量 + Checkpoint 统一存储）

---

## 架构概要

```
CLI (Click) → Services → Agents (DeepAgents) → Pipeline (LangGraph) → Storage (PostgreSQL + pgvector)
                              ↓
                        LLM (Claude API)
                        Embedding (sentence-transformers, local)
```

四个核心框架的分工：
- **LangChain**: 文档加载、文本分割、Embeddings 封装、Tool 定义
- **LangGraph**: 有状态流水线（摄入/查询）、Checkpoint 持久化
- **DeepAgents**: 多 Agent 深度推理（分类/关联/摘要/问答）
- **Claude API**: 核心推理引擎

PostgreSQL 统一存储：业务元数据（MetadataStore）+ 向量检索（pgvector，VectorStore）
+ HIL Checkpoint（PostgresSaver）全在一个库，备份/事务一致。

---

## 开发原则（必须遵守）

### 文档驱动开发
1. **先更新文档，再写代码。** 任何功能变更、新增模块、架构调整，必须先更新 `docs/requirements.md` 和/或 `docs/design.md`
2. 两个文档的角色：
   - `requirements.md`: 回答"做什么"——用户场景、功能需求、非功能需求
   - `design.md`: 回答"怎么做"——架构、模块设计、数据流、技术选型
3. 每个 Phase 开始时，在需求文档中明确本 Phase 的范围
4. 每个 Phase 结束时，在 `CLAUDE.md` 中记录经验教训

### 渐进式开发
- Phase 1 只做最小可用：文件监听 + 语义搜索 + CLI
- 每个 Phase 加一层智能，不超前设计
- 代码保持简单，不为"未来可能需要"而写

### 代码风格
- 类型标注：所有公共函数必须有完整的类型标注
- 文档字符串：使用 Google style docstring
- 异步优先：IO 操作（文件、数据库、API）使用 async/await
- 错误处理：明确区分可恢复错误和致命错误，不使用裸 `except:`
- 日志：使用 `loguru`，关键路径必须记录 INFO 级别日志
- 命名：遵循 PEP 8，文件名用 snake_case，类名用 PascalCase

### 测试策略
- 存储层必须有单元测试（用临时目录，不依赖真实数据库）
- 核心流水线必须有集成测试（可以 mock LLM 调用）
- Agent 输出格式必须有单元测试（mock LLM 响应）
- CLI 命令必须有集成测试（Click CliRunner）
- 测试文件镜像源码目录结构：`tests/test_storage/test_vector_store.py`

---

## 环境与工具

### Python 环境
```powershell
# 创建虚拟环境
python -m venv .venv
.venv\Scripts\Activate.ps1

# 安装依赖
pip install -r requirements.txt
```

### 关键依赖
```
langchain
langgraph
langgraph-checkpoint-postgres
deepagents
psycopg[binary]        # PostgreSQL 驱动
pgvector               # PostgreSQL 向量扩展
fastapi
click
loguru
pydantic
pydantic-settings
pyyaml
watchdog
markdown
feedparser
networkx
tiktoken
```

### 开发工具
- **Lint/Format**: ruff（配置在 pyproject.toml）
- **测试**: pytest + pytest-asyncio
- **环境变量**: `.env` 文件（通过 python-dotenv 加载）

### 运行命令
```powershell
# 激活环境
.venv\Scripts\Activate.ps1

# 运行 CLI
python -m brain.cli.main --help

# 运行测试
pytest tests/ -v

# 运行 lint
ruff check brain/
```

---

## 项目约定

### Git 约定（未来启用）
- 分支命名：`phase/N-short-desc` 或 `feature/short-desc`
- Commit 信息：中文描述，格式 `[模块] 简短描述`
- 不提交：`.venv/`、`data/`、`.env`、`__pycache__/`、`*.db`

### 文件组织
- `brain/models.py` 是所有数据模型（Pydantic）的唯一定义处
- 每个模块暴露的公共接口通过 `__init__.py` 控制
- 配置项统一在 `brain/config.py` 中定义，不允许在业务代码中直接读环境变量

### 数据模型约定
- 所有 ID 使用 UUID4 字符串
- 时间戳统一使用 ISO 8601 格式字符串（PostgreSQL 兼容）
- 置信度/强度使用 0.0 ~ 1.0 的 float

---

## 个人偏好

### 编程习惯
- 函数优先于类：纯函数能解决的不用类，有状态的才封装为类
- 异步优先：涉及 IO 的操作一律写 async 函数
- 依赖注入：不在类内部创建外部依赖（如数据库连接），通过构造函数传入
- 结构化输出：AI 调用的输出尽量用 Pydantic 模型约束，不用自由文本

### 注释风格
- 注释用中文，变量/函数名用英文
- "为什么这样做"的注释比"做了什么"更重要
- 复杂的算法逻辑必须注释解释思路

### 命名偏好
- 避免缩写：`metadata_store` 而不是 `meta_store`
- Boolean 变量用 `is_` / `has_` / `should_` 前缀
- 集合变量用复数形式：`notes`、`tags`、`connections`

---

## 注意事项

### 平台注意（Windows）
- 文件路径使用 `pathlib.Path`，不要硬编码 `/` 或 `\`
- watchdog 在 Windows 上使用 `ReadDirectoryChangesWatcher`
- PowerShell 不支持 `&&` 链式操作，用 `; if ($?) { ... }` 替代
- 虚拟环境的 Python 路径: `.venv\Scripts\python.exe` 而非 `bin/python`
- **loguru 文件日志不用 rotation（按大小轮转）**：loguru 的轮转靠 `os.rename` 重命名当前日志文件，但 Windows 不允许重命名“被进程占用的文件”（`enqueue=True` 的写入线程长期持有句柄），导致 `PermissionError [WinError 32]` 刷屏。本地项目日志量小，改用 `retention="7 days"` 按天数清理，不在运行时重命名文件，彻底避开文件锁

### API 调用注意
- Anthropic API Key 通过环境变量 `ANTHROPIC_API_KEY` 传入
- 不要将 API Key 硬编码到代码或配置文件中
- 开发阶段注意 API 调用成本，避免不必要的重复调用

### 数据安全
- `data/` 目录包含日志，已加入 `.gitignore`
- 数据库（PostgreSQL brain 库）是唯一数据源，定期备份 `pg_dump brain`
- 测试用独立 schema 隔离（每个测试创建 `test_<uuid>` schema，测完 DROP），不污染主数据
- 删除操作实现软删除（`status='deleted'`），保留原始数据

---

## 迭代记录

### Phase 1 ✅ (2024-08-12 完成)
- 目标：核心 MVP — 文件摄入 + 语义搜索 + CLI 问答
- 范围：FR1-FR5
- 成果：5 个 CLI 命令可用，LangGraph 流水线 parse→chunk→embed→index
- 经验：
  - `pip install -e .` 需要 `[tool.setuptools.packages.find]` 排除 `data/` 目录
  - ChromaDB + sentence-transformers 非 daemon 线程导致进程不退，用 `os._exit(0)` 解决
  - HuggingFace 被墙，设置 `HF_ENDPOINT=https://hf-mirror.com` 或写入 `.env`（已过时：embedding 已切 SiliconFlow API，不再用本地模型，此配置已清理）
  - LLM 调用统一走 `brain/llm.py`，不直接调原生 SDK
  - 数据路径用 `Path(__file__).resolve().parent.parent` 动态定位项目根目录

### Phase 2 ✅ (2024-08-12 完成)
- 目标：DeepAgents 智能处理 — 自动分类 + 关联发现
- 范围：FR6-FR10
- 成果：classify + connect 节点集成到 LangGraph 流水线
- 经验：
  - DeepSeek 对结构化 JSON Schema 的理解需要具体示例，不能只给格式描述
  - note_id 必须在流水线第一步就确定（UUID），不能在中间改变（会导致外键不一致）
  - Agent 的 Pydantic 输出模型要简单明了，嵌套不宜过深
  - 标签搜索用模糊匹配（substring）比精确匹配实用得多

### Phase 3 ✅ (2024-08-13 完成)
- 目标：主动服务 + Web UI + 智能问答 + 会话记忆
- 范围：FR11-FR29
- 成果：FastAPI + Vue3 前后端分离；SSE 流式问答（思考/工具/答案分区）；会话管理；
  三层记忆（工作窗口/向量检索/HIL 知识沉淀）；文件监听；RSS 订阅；SM-2 复习；
  知识图谱可视化；定时任务调度；92 个测试全绿
- 经验：
  - BGE 模型最大 512 token，长文本 embedding 必须分块或截断（embedding 层做兜底）
  - Gradio 6 破坏性变更多（show_copy_button 移除、launch 不阻塞），换 FastAPI+Vue 更稳
  - LangGraph 流式模式下 tool_calls 分片到达（name 和 args 分开），需按 index 累积合并
  - stream_mode="messages" 会混入 ToolMessage，需按 class 名 + tool_call_id 过滤
  - Vue 3 流式更新必须用 reactive() 包装消息对象，普通对象 push 进数组后改属性不触发渲染
  - DeepAgents 的 interrupt_on + SqliteSaver checkpointer 实现 HIL：中断事件经 __interrupt__ 透出，用 Command(resume=decisions) 恢复，thread_id 必须等于 session_id
  - DeepSeek 对"条件性委派子智能体"（"如果值得就做"）经常跳过，指令要写成"必须执行"
  - SQLite 连接跨线程共享必须加锁（LangGraph 工具并行执行会并发访问）
  - MetadataStore 从 aiosqlite 改同步 sqlite3 后，测试 fixture 和全部 await 调用要同步改
  - os._exit(0) 解决 ChromaDB 非 daemon 线程卡进程退出，但测试临时目录清理用 ignore_cleanup_errors
  - 批量查询方法（get_tag_counts/get_all_connections_flat/get_note_degree_map）应优先于 N+1 遍历，
    但 CLI status/connections 仍遗留 N+1 调用——Phase 4A 修复
  - FastAPI @app.on_event 已废弃，测试有 DeprecationWarning——Phase 4A 迁移到 lifespan

### Phase 5 🔵 (2024-08-13 进行中)
- 目标：生产化加固——从「能跑」到「可维护」
- 范围：FR42-FR60（拆 5A/5B/5C/5D/5E/5F 六个子阶段）
- 5A：可观测性（trace_id + JSON 日志 + metrics 表 + 健康检查 + Observability 页面）
- 5B：成本治理（Token 计费 + 预算熔断 + 成本报表）
- 5C：容灾备份（数据备份/恢复 + LLM 容灾 + 记忆清理）
- 5D：评估闭环（离线测试集 + Bad Case 回流 + LLM-as-Judge）
- 5E：提示词外部化（prompts/*.yaml + 配置集中化）
- 5F：RAG 增强（BM25+Rerank+查询改写）
- 约束：本地优先，不引入 K8s/Redis/Kafka，指标存 PostgreSQL、日志存本地文件
- 经验（5A）：
  - contextvars 透传 trace_id 比 threading.local 更适合异步生成器场景
  - FastAPI StreamingResponse 的生成器在独立上下文执行，trace_id 需在生成器内部 set
  - ruff F841 会误报闭包内使用的变量（如 trace_id 在 event_stream 闭包里用），需 noqa
  - LLM 健康检查默认 skip 避免烧配额，仅 dry_run 时真调——本地项目成本敏感
  - metrics 的 ask_count 要用 SUM(CASE WHEN metric_name='count') 而非 COUNT(*)，否则 latency 行也被数
  - 指标记录失败不抛异常（record_metric 内部 try/except），可观测性不能影响主流程
  - **contextvar 在 Starlette iterate_in_threadpool 下不可靠**：同步生成器的每次 next() 都在 copy_context() 新 context 执行，set 的值在后续 next() 丢失，token.reset() 跨 context 报 ValueError。改用闭包变量显式传 trace_id 给 record_metric，简单可靠
  - **LLM token 采集用 BaseCallbackHandler 子类**（不能鸭子类型，LangGraph callback_manager 要求 raise_error 等属性）。DeepSeek 流式模式下 token usage 在 message.usage_metadata 而非 llm_output.token_usage，回调需两种途径都试
  - HIL 多 proposals：DeepSeek 一次可提议多个知识片段，LangGraph 要求 decisions 数量 = action_requests 数量，前端需为每个 proposal 展示卡片逐一收集决策
  - **调用链需双表设计**：metrics 表存数值（latency/token/count，供看板聚合），trace_events 表存完整入参出参（供调用链回放），两者通过 trace_id 关联。单表混存会导致统计查询被超长文本拖慢
  - LangChain BaseCallbackHandler 的 on_chat_model_start 收到 messages 是 list[list[BaseMessage]]（嵌套），提取 prompt 文本要处理嵌套结构
  - LLM/工具的入参出参要截断（2000 字符），否则长 prompt 会撑爆 SQLite，且前端渲染卡顿
- 经验（5B）：
  - **成本数据复用 trace_events 表**，不新建 llm_usage 表——token_usage JSON 里加 cost 字段即可，成本天然随 trace_id 关联，用 json_extract 聚合查询
  - **预算用量应为独立计数器，不从审计日志聚合**：早期用 SUM(json_extract) 从 trace_events 聚合今日 token，“重置”变成删历史记录，破坏了调用链回放数据。改为独立 usage_counters 表（today/month/total 三行 + period_key 跨天轮转），on_llm_end 时 UPSERT 累加，重置只清零计数器不删 trace_events。回填逻辑幂等（仅计数器为空时从 trace_events 初始化）
  - SQLite 的 json_extract 可直接从 JSON 字段提取 cost：`SUM(json_extract(token_usage, '$.cost'))`，无需应用层解析
  - **预算熔断在 API 入口检查**（ask/stream/resume），超限返 429；recursion_limit 通过 stream/invoke 的 config 传入防死循环，两层防护
  - DeepSeek 实际返回的 model 名是 `deepseek-v4-flash`（不是配置的 `deepseek-chat`），价格表要兼容别名
  - 历史数据无 cost 字段不影响新数据——只有 5B 之后的 LLM 调用才记成本，聚合时 NULL 自动忽略
  - **DeepSeek v4 定价分空闲/高峰 + 缓存命中/未命中**：缓存命中价便宜 30 倍，usage_metadata.input_token_details.cache_read 字段提取命中数。实际调用中 prompt 80%+ 命中缓存，成本比“全未命中”估算低一个数量级
  - calc_token_cost 用 keyword-only 参数（peak_hours、cache_hit_tokens）保持向后兼容，默认空闲未命中（最保守常用场景）
- 经验（5D）：
  - **评估打分以规则为主**（关键词命中+来源正确性+完整性），不依赖 LLM，零成本可重复跑；LLM-as-Judge 为辅提供主观质量趋势
  - Golden Dataset 存 YAML 可版本管理（进 git），不进数据库——测试集是要 review 和迭代的产物
  - 来源正确性从 trace_events 的 tool_call input/output 提取 note_id，复用 5A 的调用链数据，无需额外埋点
  - bad case 收集失败不抛异常（collect_bad_case 内部 try/except），评估闭环不能影响主流程
  - LLM-as-Judge 的 prompt 要求严格 JSON 输出，但要容错——LLM 可能输出多余文本，用 find('{')..rfind('}') 提取 JSON 块
  - scheduler 加 weekly_eval 周任务抽样，成本可控（10% 抽样 + 单次 Judge 调用）
  - **测试集存数据库而非文件**：golden_cases/bad_cases 表支持页面 CRUD，YAML 仅作种子导入（首次 seed）。运行时全部走数据库，避免文件读写并发问题，页面实时增删改查
  - **MetadataStore 双后端兼容**：通过 config.database.host 切换 SQLite/MySQL，_exec 方法自动翻译占位符（?→%s）、UPSERT（ON CONFLICT→ON DUPLICATE KEY）、json_extract（→CAST(JSON_UNQUOTE(JSON_EXTRACT)) AS DECIMAL）。测试 fixture monkeypatch host=None 强制 SQLite 隔离
  - **SQLite→MySQL 迁移不能手写 DDL**：表结构要从 SQLite PRAGMA table_info 动态读取生成，否则列名/类型必不一致。TEXT 列做 PK/索引需指定 VARCHAR(255) 长度，MySQL 严格模式不允许 TEXT 列 DEFAULT
- 经验（5E）：
  - **提示词存数据库而非 YAML**：提示词是需在线迭代的运营资产（页面编辑、即时生效、版本可追溯），YAML 需重启且无法页面管理。参照 golden_cases 表的「配置存库 + 页面 CRUD」先例，新增 prompts 表（prompt_key PK / content / is_template / version / enabled）
  - **提示词读取层带进程内缓存**：Agent 运行时高频读取 system_prompt，每次查库有开销。brain/prompts.py 用字典缓存，upsert 时 reload_prompt(key) 清单条缓存实现即时生效。get_prompt 找不到时回退到 prompt_defaults.py 的默认值并告警，不崩
  - **BaseAgent.system_prompt 从类属性改 property**：子类只需定义 name（=prompt_key），property getter 调 get_prompt(self.name)。classifier/connector 删掉 system_prompt 类属性，researcher 的 3 处 system_prompt= 改读 get_prompt()
  - **含占位符的提示词用 is_template 标记**：judge 的提示词有 {question}/{answer}/{context}，is_template=1，走 get_prompt_template(key, **kw) 用 str.format 渲染；其余 5 个是纯文本直接读。注意 str.format 遇到 JSON 示例里的 {{}} 需双写转义
  - **system/user 角色必须分离**：原 BaseAgent 把 system_prompt 和 user_prompt 拼成单字符串用 llm.invoke(str) 调用，全部被当 HumanMessage，system 角色没发挥高优先级作用。改为 [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt+schema)] 两条消息。judge 的提示词用 ---USER--- 标记 system/user 边界，运行时 split 拆分（角色说明+评分标准+输出格式=system，问题/回答/上下文=user）
  - **MySQL 长连接必须用 autocommit=True**：autocommit=False 时第一次 SELECT 隐式开启事务，REPEATABLE READ 隔离级别下后续读都卡在事务开始时的快照，看不到其他连接的提交（表现为 server 进程读不到外部脚本清理的数据）。改为 autocommit=True，每条语句自动提交，读操作始终看最新数据。原有 37 处 self._conn.commit() 对 autocommit=True 无害（空操作）。_synchronized 锁已保证单线程串行，UPSERT 累加无并发竞态
  - **threading.Lock 不可重入会死锁**：update_prompt 持锁后调 get_prompt（也要同一把锁），Lock 不可重入导致死锁。改为 threading.RLock（可重入锁），允许同一线程多次获取。凡是「同步方法内部调用另一个同步方法」的场景都必须用 RLock
  - **前端需引入 Vue Router 实现页面独立 URL**：早期所有页面共用 `/` 地址靠 activeView 状态切换，刷新丢失、地址不变。引入 vue-router 后每个页面有独立路由（/ask/:sessionId?、/search、/admin/prompts 等）。Ask 组件需访问会话列表/seed，由 App.vue 直接渲染（路由 component 用空占位 { render: () => null }）；其余页面走 <router-view>。后端加 catch-all 路由 /{full_path:path} 做 SPA fallback，非 /api 路径都返回 index.html，深层路由刷新不 404
- 经验（5F）：
  - **BM25 不双写 chunk 全文**：chunk 内容只存 ChromaDB，SQLite 仅有 content_preview(200字)。BM25 索引标题+预览即可覆盖主要关键词，双写全文会引入数据一致性问题。BM25 价值在精确关键词命中（专有名词/代码标识符），语义匹配交给向量检索
  - **SQLite FTS5 中文分词陷阱**：默认 unicode61 分词器对 CJK 按字切分，“RAG 优化”会切成 RAG/优/化 三个 token，“教程”切成教/程。MATCH '教程' 查不到（索引里没“教程”这个 token）。解决方案：FTS 结果为空时用 LIKE '%query%' 兜底，英文走 FTS（有 BM25 排序），中文走 LIKE（保证召回，牺牲排序精度）
  - **FTS5 contentless 表的 contentless_delete=1 有版本要求**，旧 SQLite 报 `contentless_delete=1 requires a contentless table`。改用普通 FTS5 表（独立存索引数据，由 _sync_fts_note 维护同步），兼容性更好
  - **bm25() 函数返回值极小**（1e-06 量级），round(,4) 后变 0.0，但不影响 ORDER BY 排序（原始值有区分度）。RRF 融合只用排名不用绝对分，所以 score=0.0 对融合无影响
  - **Rerank 走 SiliconFlow /v1/rerank API 而非本地模型**：现有 embedding 已走 SiliconFlow API，本地 cross-encoder 会引入 GB 级模型下载，违背轻量原则。复用现有 SILICONFLOW_API_KEY，零新依赖。OpenAI SDK 不直接支持 /rerank 端点，用 client._client.post 走原始 HTTP
  - **QueryRewriter 必须懒加载 LLM**：__init__ 里调 get_chat_model() 会在测试环境（无 API key）报错。改为首次 rewrite() 时才初始化 LLM，build_hybrid_searcher 构造时不触发任何外部调用
  - **HybridSearcher 调用 BM25 要双保险 try/except**：bm25_search 内部已有 try/except 返回空列表，但 mock side_effect 会绕过内部处理直接抛异常。_retrieve_and_fuse 调用处再加一层 try/except，任一环节失败都不阻塞主流程（降级为纯向量）
  - **测试 fixture 必须强制 SQLite 隔离**：client fixture 创建新 AppConfig 但没设 database.host=None，会读 .env 的 BRAIN_DB_HOST 连真实 MySQL，导致测试间数据污染（test_delete_session 因残留数据失败）。新增 `cfg.database.host = None` 强制 SQLite，并重置 _hybrid_searcher 全局单例。这是既有问题，5F 新增全局变量时顺带修复
  - **PowerShell Set-Content 默认 GBK 编码会破坏中文**：用 `Get-Content -Raw | Set-Content` 批量替换文本时，默认编码把 UTF-8 中文写成 GBK，导致 SyntaxError。必须用 Python 重写文件（`open(path,'w',encoding='utf-8')`）或 PowerShell 指定 `-Encoding utf8`。教训：涉及中文的文件批量替换优先用 Python 而非 PowerShell
  - **提示词种子要支持增量补充**：_seed_prompts 原本仅空表时写入全部默认值，旧库升级时新增的 query_rewriter 不会被补充。改为「空表写全部 + 非空表补充缺失 key」，让 5F 新增的提示词能自动出现在已初始化的库里
  - **检索链路双调用方统一**：researcher.search_notes 工具和 server /api/search 原本各自调 VectorStore.search，5F 抽出 HybridSearcher 统一入口，两者都注入。CLI 的 _get_search_components 返回三元组，所有解包处同步更新
  - **所有提示词一律从数据库读取，代码不得硬编码**：5E 外部化了 7 个（classifier/connector/researcher/title_writer/knowledge_extractor/judge/query_rewriter），但 digest.py 的 `DAILY_DIGEST_PROMPT`/`WEEKLY_TREND_PROMPT`（硬编码 PromptTemplate）和 cli/main.py `_ask_simple` 的内联 f-string prompt 被遗漏。补全为 10 条（新增 daily_digest/weekly_trend/cli_ask），全部走 `get_prompt_template`。教训：外部化时要全局搜 `PromptTemplate`/`llm.invoke(prompt)`/`SystemMessage(content=` 等模式，不能只看 BaseAgent 子类——直接 invoke LLM 的调用点（digest/cli/judge/query_rewriter）同样要纳入
- 经验（4B）：
  - **书签去重的 file_hash 必须与流水线一致**：BookmarkSource 预检查去重用的 file_hash，必须和 ingest_text_sync 内部计算方式完全一致。pipeline 会把 content 包装成 `# {title}\n\n{content}` 再算 hash，所以预检查的 hash 也要基于包装后的文本，否则预检查漏判、重复摄入
  - **ingest_text_sync 的标题包装陷阱**：传 `content=url, title=title` 时，pipeline 内部拼成 `# {title}\n\n{url}` 作为 raw_text。书签源不能自己拼 `# {title}\n\n{url}` 再传（会变成双标题），只传纯 URL 让 pipeline 包装，保证 file_hash 一致
  - **source_type 通过 state 透传**：IngestionState 加 source_type 字段，_index_node 优先用显式传入的（如 BOOKMARK），否则按 source_path 推断（文件=MARKDOWN，空=CLI）。TypedDict 运行时不强制，旧构造点用 state.get(key, '') 兑底也不会 KeyError
  - **标签云字号按计数权重**：前端 Tags.vue 用 `fontSize = 12 + (count/maxCount)*20` 让高频标签字号大，点击跳转 /search?tag=xxx。Search.vue 加 onMounted 读 route.query.tag 自动填充标签过滤
  - **笔记内容编辑不做**：内容存在 ChromaDB 分块，原地改内容需重建向量（删旧 chunk + 重新分块嵌入），复杂度高。4B 只做标题/标签/关联编辑，内容编辑走重新摄入流程
- 经验（5C-FR51）：
  - **优先用 SDK 原生重试，别包装 tenacity**：ChatOpenAI/ChatAnthropic 的 `max_retries` 参数透传给底层 OpenAI/Anthropic SDK，SDK 自带完善的 HTTP 层重试——自动重试 429/5xx/408/409 + 指数退避 + 随机抖动，鉴权失败(401)/参数错误(400)不重试。实测 OpenAI SDK 的 `_should_retry` 方法已按状态码精确分类。应用层再包 tenacity 是重复造轮子，且会导致 SDK 重试 + tenacity 重试的三重重试（浪费配额）
  - **base.py 保留外层重试是必要的**：SDK 只管 HTTP 层（请求成功就返回），但 LLM 返回了内容、JSON 解析失败是业务层问题，SDK 不会重试。base.py 的外层 for 循环专门处理「解析失败→重新调 LLM 拿新输出」，与 SDK 的网络重试职责不重叠。两层各管各的
  - **显式传 max_retries 而非用默认**：ChatOpenAI 默认 max_retries=None（透传给 SDK，SDK 默认 2 次），在 `llm.py` 初始化时显式传 `cfg.llm.max_retries=3` 让次数可控可配
  - **中间件选型原则**：先用原生 SDK 能力，不够再考虑第三方库。LangChain 生态的 ChatModel 已经封装了 provider SDK 的重试/超时/流式，应用层应尽量用配置参数而非包装函数
- 经验（base.py 重构）：
  - **结构化输出用 LangChain 的 PydanticOutputParser，别手写**：原 base.py 手写了 `_build_user_prompt_with_schema`（拼格式说明+示例）、`_parse_json`（去 markdown 包裹+正则提取）、`_describe_model`/`_build_example`/`_example_value`/`_type_to_str`（递归构建示例）共约 100 行。LangChain 的 `PydanticOutputParser` 一个类全覆盖：`get_format_instructions()` 生成标准 JSON Schema 格式说明，`parse()` 解析输出为 Pydantic 实例（自动处理 markdown 包裹）
  - **PydanticOutputParser.parse 不做激进正则提取**：手写 `_parse_json` 用 `re.search(r'\{.*\}')` 能从「前后大段说明文字」里抠出 JSON，但 LangChain parser 要求输入是纯 JSON 或 markdown 包裹，不做正则提取。这不是缺陷而是设计——prompt 已要求 LLM 只输出 JSON，乱输出的 LLM 应交由 base.py 外层重试重新调，而不是激进解析可能错误的 JSON
  - **重构要同步改测试**：原测试直接调用 `_build_user_prompt_with_schema` 和 `_parse_json`，重构后这些方法删除，测试改为验证 `_parser.get_format_instructions()` 和 `_parser.parse()` 的等价行为。测试用例从「验证手写解析逻辑」转为「验证 LangChain parser 行为」，更贴近实际使用
- 经验（PostgreSQL 迁移）：
  - **MySQL + ChromaDB → PostgreSQL + pgvector 一次性迁移**：业务元数据 + 向量检索 + LangGraph Checkpoint 全部迁进一个 PostgreSQL 库，去掉 ChromaDB/SQLite/MySQL 三个独立存储。VectorStore 接口不变只换实现（调用方零改动），MetadataStore 从双后端简化为单后端
  - **psycopg 3 用 dict_row 兼容旧代码**：原来 sqlite3.Row / pymysql DictCursor 返回 dict（`r["col"]` 访问），psycopg 默认返回 tuple。设 `row_factory=dict_row` 后行为一致，业务代码无需改
  - **JSONB 列 vs TEXT 列**：Postgres 的 `->>` / `->` 操作符只支持 JSONB/JSON 类型，TEXT 不行。存 JSON 的列（timeline/token_usage/details）必须用 JSONB。psycopg 读 JSONB 列时自动解析为 Python dict/list，不能再 `json.loads`——加 `_parse_json` 辅助方法兼容（JSONB 已是对象直接返回，TEXT 字符串才 json.loads）
  - **AUTOINCREMENT → SERIAL**：SQLite 用 `INTEGER PRIMARY KEY AUTOINCREMENT`，Postgres 用 `SERIAL PRIMARY KEY`（底层是序列）
  - **INSERT OR IGNORE/REPLACE → ON CONFLICT**：Postgres 不支持 SQLite 的 `INSERT OR IGNORE`/`INSERT OR REPLACE`，要用 `INSERT ... ON CONFLICT (cols) DO NOTHING/UPDATE SET`。冲突列必须是唯一约束/PK
  - **cur.lastrowid → RETURNING id + fetchone**：psycopg 3 的 cursor 没有 `lastrowid` 属性，要在 INSERT 末尾加 `RETURNING id`，用 `cur.fetchone()["id"]` 取回。共 12 处，批量改时要在 SQL 字符串结束引号前插入（RETURNING 必须在 ON CONFLICT 之后，即 SQL 最后）
  - **psycopg 字面量 % 转义**：`to_char(col, '%H')` 的 `%H` 会被 psycopg 当占位符报错。和原 pymysql 一样要把字面量 `%` 转义成 `%%`（占位符 `%s` 保留）。`_exec` 里先 `?`→`%s`，再转义 `%`→`%%`，最后恢复 `%s`
  - **strftime 格式串 ≠ to_char 格式串**：SQLite `strftime('%H', col)` 的 `%H` 不能直接给 Postgres `to_char`（要用 `'HH24'`）。格式串要单独转换，或直接改源码用 Postgres 原生写法。实际只有一处 SQL 用了 strftime，直接改成 `to_char(created_at::timestamp, 'HH24')`
  - **pg_trgm 替代 FTS5**：BM25 关键词检索从 SQLite FTS5 表改成 pg_trgm GIN 索引 + ILIKE。pg_trgm 索引直接挂 notes 表（写入即同步，无需 `_sync_fts_note`），`_like_query` 用 `similarity()` 排序。中文兼容性好（trigram 按 3 字符切分，CJK 友好）
  - **测试用独立 schema 隔离**：每个测试创建 `test_<uuid>` schema，dsn 的 `search_path=test_xxx,public`（含 public 才能找到 vector/jsonb 等扩展类型），测完 DROP SCHEMA CASCADE。比临时 SQLite 文件更快、更干净，多测试并行不干扰
  - **PostgresSaver 不能用 from_conn_string 直接拿**：`PostgresSaver.from_conn_string()` 返回 contextmanager，不能直接 `.setup()`。要手动建连接 `PostgresSaver(psycopg.connect(dsn, autocommit=True))` 后再 setup
  - **表名三层前缀约定区分存储层级**：业务元数据（MetadataStore，19 张）无前缀（notes/sessions/messages，是主体）；向量检索（VectorStore，3 张）`vec_` 前缀（vec_note_chunks/vec_conversation_memory/vec_fragment_memory）；检查点（PostgresSaver，4 张）`checkpoint_` 前缀（LangGraph 自动建）。光看表名一眼区分用途，不用查注释。改名时只改 VectorStore（业务表是主体不动，checkpoint 表是第三方的不动）
  - **向量表改名要兼容已初始化的库**：`_migrate_table_names` 用 `to_regclass()` 探测旧表是否存在，旧表存在且新表不存在时 `ALTER TABLE RENAME`。关键顺序：迁移必须在 `CREATE TABLE IF NOT EXISTS vec_xxx` 之前——否则新表已建（空），条件不满足跳过迁移。已有数据的旧库要先 DROP 空新表再 RENAME
  - **PostgreSQL COMMENT ON 是幂等的**：`COMMENT ON TABLE/COLUMN` 重复执行只更新不报错，适合在 `_create_tables` 末尾统一加注释。注释失败用 try/except 兜底（注释不能阻塞建表）。表注释说明层级和用途，列注释说明枚举值/单位/关联表，数据库可直接 `\d+ tablename` 查看
  - **测试 schema 残留是 teardown 连接未关**：VectorStore fixture 的 yield 后直接 DROP SCHEMA，但 VectorStore 的 psycopg 连接还开着（持有 schema 引用），DROP 可能因锁失败留下垃圾。修复：yield 后先 `vs._conn.close()` 再 DROP。曾累积 70 个 test_ schema 残留，根因即此
  - **生成时强制结构化 > 生成后解析**：PydanticOutputParser 是「生成后解析」（LLM 输出文本→parser 解析），仍可能解析失败。`with_structured_output(method="function_calling")` 是「生成时强制」（SDK 用 function calling 让模型在生成时就遵循 schema），invoke 直接返回 Pydantic 实例，不存在解析环节。后者更可靠，base.py 连外层重试循环都省了
  - **DeepSeek method 实测选择**：用真实 API key 实测，`function_calling` 成功直接返回实例；`json_mode` 失败（要求 prompt 含 "json" 字样，多余约束）。故选 `function_calling`。不要凭文档猜，要真调一次验证
  - **base.py 三次演进**：手写 `_parse_json`（正则提取+json.loads，约 100 行）→ PydanticOutputParser（get_format_instructions + parse，约 105 行）→ with_structured_output（3 行核心逻辑，约 90 行）。每一步都删掉更多手写代码，最终方案最简洁，职责全交给 SDK
  - **with_structured_output 后测试要变**：不再有「解析」环节，无法用 mock 文本测试解析鲁棒性。测试改为验证 output_model 配置正确、_structured_method 配置正确、to_tags 能处理 Pydantic 实例。实际的结构化输出正确性靠真实 API 调用保证（集成测试或手动验证）
- 经验（API 层按业务域拆包）：
  - **业务域自包含包 > 单文件大杂烩**：原 `brain/api/server.py` 1195 行 56 个端点混在一起，拆成 `routes/{notes,search,ask,sources,scheduler,observability,eval,prompts,review}/` 每个包含 `router.py`（端点）+ `models.py`（Request/Response）。增删改某业务只动一个包，不牵扯其他
  - **deps.py 集中管单例 + 访问器**：原全局变量 `_vector_store/_metadata_store/...` 散在 server.py，每个端点手写 `_init()`。拆后 `deps.py` 持有单例 + `get_*()` 访问器自动触发初始化，路由不再写 `_init()`
  - **兼容垫片用模块级 `__getattr__`/`__setattr__`**：`server.py` 改为垫片 re-export app，但测试 fixture 和 `brain.prompts` 历史上读 `server_module._metadata_store`。用模块级 `__getattr__` 动态代理到 deps，`__setattr__` 重定向赋值到 deps，保证 fixture 重置 `server_module._xxx` 真正改的是 deps 源变量（路由用 deps 访问器读取）。注意 `__setattr__` 要放行非代理名，否则模块正常赋值被拦
  - **prompts._get_store 只读不初始化**：原 `from brain.api.server import _metadata_store` 读的是 None（未 _init），回退默认值。重构时误改成 `get_metadata_store()`（会触发 `_init()`），导致 test_base.py 的纯文本 Agent 测试（system_prompt 属性读取）反向触发真实服务初始化，污染后续 performance 测试。改为只读 `deps._metadata_store` 当前值，不触发初始化，行为与拆分前一致。教训：业务层读单例要「只读不初始化」，初始化责任留给 API 入口
  - **测试 fixture 重置改用 `deps.reset_for_test()`**：原 fixture 逐个 `server_module._xxx = None`，拆后改为 `deps_module.reset_for_test()` 一次清零。mock embedding 从 patch `server_module.get_embedding_fn` 改为 patch `deps_module.get_embedding_fn`（deps._init 调用的是自己模块的引用）
- 经验（HIL 中断消息合并）：
  - **中断与恢复的答案必须合并成一条消息**：原实现中断时 `add_message` 存第一段答案、resume 的 done 时又 `add_message` 存第二段，数据库里两条 assistant 消息，前端渲染成两条独立气泡。正确做法是中断时存 `status='pending'` 的待续消息、msg_id 暂存到 `sessions.pending_msg_id`，resume 完成时 `update_message` 同一条（合并 content + timeline + 改 status='complete'），始终只有一条消息
  - **中断时强制标记未完成 tool 为 done**：中断后不会再收到 tool_end 事件，timeline 里 `done=false` 的 tool 会永远停在「进行中」。中断保存时遍历 timeline 把未完成 tool 强制 `done=True`（后端 + 前端两处都要做，因为前端内存 timeline 和后端数据库 timeline 是两套）
  - **resume 可再次中断**：DeepAgents 多片段场景下 resume 后可能再次 yield interrupt（逐一审批）。resume 的 interrupt 分支同样要合并已流出内容到 pending 消息（status 保持 pending），不能新增消息
  - **前端复用同一 assistantMsg**：前端 resume 用同一个 `assistantMsg` 调 readStream，token 追加到同一 content，前端天然合并显示。后端只需保证持久化也合并（update 而非 add），前后端一致
  - **迁移加列要 SQLite + MySQL 双后端同步**：messages 表加 status 列、sessions 表加 pending_msg_id 列，SQLite 的 CREATE TABLE 和 _migrate 的 ALTER TABLE、mysql_schema.py 的 CREATE TABLE 三处都要改。`ADD COLUMN ... NOT NULL DEFAULT 'complete'` 会自动回填旧数据行
  - **历史消息顺序错乱根因：后端 timeline 只存 tool 不存 thought**：流式打印时前端 tool_start 会把已流出文本归档为 thought 进 timeline，顺序是「文本-工具-文本-工具」。但后端 tool_start 只 append tool 项、不归档 thought，导致持久化的 timeline 是纯工具列表，content 是全部文本拼一起。历史查看时渲染成「工具-工具-文本」。修复：后端 tool_start 也要把当前 answer_parts 归档为 thought 进 timeline 并清空 answer_parts（与前端逻辑一致），done 时 content 只存最后一段文本
  - **memory 向量用全文而非最后一段**：thought 拆分后 content 只剩最后一段文本，若直接写记忆向量会丢失前面片段的语义。done 时从 timeline 提取所有 thought 拼接 + 最后 content 作为 full_text 写 memory，保证语义检索能命中中间片段

---

## 常见问题

### 如何添加一个新的数据源？
1. 在 `brain/ingestion/sources/` 下新建文件
2. 实现 `SourceProtocol` 接口（定义在 `brain/models.py`）
3. 在 `IngestionPipeline` 中添加对应的解析节点
4. 在 `config.yaml` 的 `sources` 段添加配置
5. 更新 `requirements.md` 和 `design.md`

### 如何添加一个新的 Agent？
1. 在 `brain/agents/` 下新建文件，继承 `BaseAgent`
2. 实现 `async def execute(self, input: X) -> Y` 方法
3. 在 `brain/agents/__init__.py` 中注册
4. 在流水线或服务中调用
5. 更新 `design.md` 的 Agent 层描述

### 如何在开发中避免消耗 API 额度？
- 设置环境变量 `BRAIN_DRY_RUN=true` 使用 mock LLM 响应
- 单元测试中始终 mock LLM 调用
- 使用 `--dry-run` CLI flag 跳过 LLM 调用
