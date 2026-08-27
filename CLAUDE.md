# CLAUDE.md — 个人知识管家（第二大脑）

> 最后更新: 2024-08-13

---

## 项目概述

**Brain（个人知识管家）** 是一个本地优先、AI 驱动的个人知识管理系统。
核心目标：把碎片信息变成可检索、可关联、可生长的知识网络。

- **项目根目录**: `D:\projects\deep_agents`
- **主包名**: `brain`
- **Python 版本**: 3.11+
- **平台**: Windows 11 (PowerShell 5.1)

---

## 架构概要

```
CLI (Click) → Services → Agents (DeepAgents) → Pipeline (LangGraph) → Storage (ChromaDB + SQLite)
                              ↓
                        LLM (Claude API)
                        Embedding (sentence-transformers, local)
```

四个核心框架的分工：
- **LangChain**: 文档加载、文本分割、Embeddings 封装、Tool 定义
- **LangGraph**: 有状态流水线（摄入/查询）、Checkpoint 持久化
- **DeepAgents**: 多 Agent 深度推理（分类/关联/摘要/问答）
- **Claude API**: 核心推理引擎

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
deepagents
chromadb
sentence-transformers
click
loguru
pydantic
pydantic-settings
pyyaml
watchdog
markdown
feedparser        # P2
networkx          # P2
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
- 时间戳统一使用 ISO 8601 格式字符串（SQLite 兼容）
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
- ChromaDB 在 Windows 上需要 `chromadb` 的 SQLite 绑定正常
- watchdog 在 Windows 上使用 `ReadDirectoryChangesWatcher`
- PowerShell 不支持 `&&` 链式操作，用 `; if ($?) { ... }` 替代
- 虚拟环境的 Python 路径: `.venv\Scripts\python.exe` 而非 `bin/python`

### API 调用注意
- Anthropic API Key 通过环境变量 `ANTHROPIC_API_KEY` 传入
- 不要将 API Key 硬编码到代码或配置文件中
- 开发阶段注意 API 调用成本，避免不必要的重复调用

### 数据安全
- `data/` 目录包含用户的真实笔记，已加入 `.gitignore`
- 测试时使用临时目录 (`tempfile.TemporaryDirectory`)，不操作真实数据
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
  - HuggingFace 被墙，设置 `HF_ENDPOINT=https://hf-mirror.com` 或写入 `.env`
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
- 约束：本地优先，不引入 K8s/Redis/Kafka，指标存 SQLite、日志存本地文件
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
