"""元数据存储（同步，PostgreSQL）。

管理笔记元数据、标签、关联关系、摄入日志等全部业务数据的 CRUD 操作。
所有方法为同步调用，通过实例锁保证多线程安全。
"""

import re
import threading
from datetime import date, datetime, timedelta

from loguru import logger

from brain.models import (
    Connection,
    NoteMetadata,
    NoteStatus,
    RelationType,
    SourceType,
    Tag,
    TagCategory,
)


def _synchronized(method):
    """装饰器——用实例锁串行化数据库操作。"""

    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper


class MetadataStore:
    """元数据管理——PostgreSQL 单后端，通过实例锁保证多线程安全。"""

    def __init__(self, dsn: str | None = None):
        self._dsn = dsn
        self._conn = None
        self._lock = threading.RLock()  # 可重入锁：允许同一线程多次获取（update_prompt 调 get_prompt）

    # ---- 生命周期 ----

    @_synchronized
    def initialize(self) -> None:
        import psycopg
        from psycopg.rows import dict_row

        if not self._dsn:
            from brain.config import get_config
            self._dsn = get_config().database.dsn
        # autocommit=True：每条语句自动提交，读操作始终看最新数据
        # dict_row：返回 dict（兼容旧的 r["col"] 访问风格）
        self._conn = psycopg.connect(self._dsn, autocommit=True, row_factory=dict_row)
        logger.info("MetadataStore 已连接 PostgreSQL")
        self._create_tables()

    @_synchronized
    def close(self) -> None:
        if self._conn:
            self._conn.close()
            logger.info("MetadataStore 已关闭")

    def _exec(self, sql: str, params=None):
        """执行 SQL，返回 cursor（调用方可 .fetchone()/.fetchall()）。

        psycopg 用 %s 占位符，业务代码用 ?，这里统一翻译。
        ON CONFLICT ... DO UPDATE SET ... excluded.col 是 Postgres 原生语法，无需翻译。
        json_extract(col, '$.k') → (col ->> 'k')::numeric（Postgres JSONB 访问）。
        """
        assert self._conn is not None
        # JSONB 列访问（Postgres 原生）
        sql = re.sub(
            r"json_extract\((\w+),\s*'\$\.(\w+)'\)",
            r"(\1 ->> '\2')::numeric",
            sql,
        )
        # 时间格式化 → Postgres to_char
        sql = re.sub(r"strftime\(([^,]+),\s*([^)]+)\)", r"to_char(\2, \1)", sql)
        # ? → %s（psycopg 占位符）
        sql = sql.replace("?", "%s")
        # 转义字面量 %（to_char 的 %H、LIKE 的 % 等），避免 psycopg 误当占位符；%s 保留
        sql = sql.replace("%s", "\x00\x00")
        sql = sql.replace("%", "%%")
        sql = sql.replace("\x00\x00", "%s")
        cur = self._conn.cursor()
        if params:
            cur.execute(sql, params)
        else:
            cur.execute(sql)
        return cur

    def _executescript(self, script: str) -> None:
        """执行多语句脚本（psycopg 单次 execute 支持多语句，无需手动分割）。"""
        assert self._conn is not None
        cur = self._conn.cursor()
        cur.execute(script)
        cur.close()

    @staticmethod
    def _parse_json(value):
        """解析 JSON 列值，兼容 JSONB（psycopg 已解析为对象）和 TEXT（需 json.loads）。"""
        if value is None:
            return None
        if isinstance(value, (dict, list)):
            return value  # JSONB 已被 psycopg 自动解析
        if isinstance(value, str):
            import json
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return None
        return value

    def _create_tables(self) -> None:
        assert self._conn is not None
        # PostgreSQL DDL
        self._executescript("""
            CREATE TABLE IF NOT EXISTS notes (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                source_type TEXT NOT NULL,
                source_path TEXT,
                file_hash TEXT,
                content_preview TEXT DEFAULT '',
                content_length INTEGER DEFAULT 0,
                chunk_count INTEGER DEFAULT 0,
                status TEXT DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                ingested_at TEXT
            );

            CREATE TABLE IF NOT EXISTS tags (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                category TEXT NOT NULL,
                is_ai_generated INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS note_tags (
                note_id TEXT NOT NULL,
                tag_id INTEGER NOT NULL,
                confidence REAL,
                PRIMARY KEY (note_id, tag_id),
                FOREIGN KEY (note_id) REFERENCES notes(id) ON DELETE CASCADE,
                FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS connections (
                id SERIAL PRIMARY KEY,
                source_note_id TEXT NOT NULL,
                target_note_id TEXT NOT NULL,
                relation_type TEXT NOT NULL,
                strength REAL DEFAULT 0.5,
                description TEXT,
                created_at TEXT NOT NULL,
                is_ai_generated INTEGER DEFAULT 0,
                FOREIGN KEY (source_note_id) REFERENCES notes(id) ON DELETE CASCADE,
                FOREIGN KEY (target_note_id) REFERENCES notes(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS ingestion_log (
                id SERIAL PRIMARY KEY,
                note_id TEXT NOT NULL,
                event TEXT NOT NULL,
                status TEXT NOT NULL,
                message TEXT,
                duration_ms INTEGER,
                timestamp TEXT NOT NULL,
                FOREIGN KEY (note_id) REFERENCES notes(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT '新对话',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                pending_msg_id INTEGER  -- HIL 中断时暂存待续消息 id（Phase 4C）
            );

            CREATE TABLE IF NOT EXISTS messages (
                id SERIAL PRIMARY KEY,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,              -- 'user' | 'assistant'
                content TEXT NOT NULL,
                timeline JSONB DEFAULT '[]',     -- JSON: 工具调用轨迹 [{kind, name, args, done}]
                created_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'complete',  -- 'complete' | 'pending'（HIL 中断态）
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS knowledge_fragments (
                id SERIAL PRIMARY KEY,
                session_id TEXT,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                status TEXT DEFAULT 'approved',  -- 'approved' | 'rejected'
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS reviews (
                note_id TEXT PRIMARY KEY,
                ease_factor REAL DEFAULT 2.5,    -- SM-2 熟练度系数（下限 1.3）
                interval_days INTEGER DEFAULT 0, -- 当前复习间隔
                due_date TEXT,                   -- 下次复习日期（ISO）
                review_count INTEGER DEFAULT 0,  -- 已复习次数
                last_quality INTEGER,            -- 上次评分 0-5
                last_reviewed_at TEXT,
                FOREIGN KEY (note_id) REFERENCES notes(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS digest_reports (
                id SERIAL PRIMARY KEY,
                report_type TEXT NOT NULL,       -- 'daily' | 'weekly'
                report_date TEXT NOT NULL,       -- 报告日期（daily: 昨日日期; weekly: 周一日期）
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(report_type, report_date)
            );

            CREATE TABLE IF NOT EXISTS rss_feeds (
                id SERIAL PRIMARY KEY,
                url TEXT NOT NULL UNIQUE,
                title TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                last_fetched_at TEXT,
                entry_count INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS rss_entries (
                id SERIAL PRIMARY KEY,
                feed_id INTEGER NOT NULL,
                entry_id TEXT NOT NULL,          -- feed 条目的唯一 ID（去重）
                title TEXT NOT NULL,
                link TEXT DEFAULT '',
                note_id TEXT DEFAULT '',         -- 摄入后生成的笔记 ID
                published_at TEXT DEFAULT '',
                content TEXT DEFAULT '',         -- 条目正文（feed content 或抓取的全文）
                UNIQUE(feed_id, entry_id),
                FOREIGN KEY (feed_id) REFERENCES rss_feeds(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_notes_status ON notes(status);
            CREATE INDEX IF NOT EXISTS idx_notes_created ON notes(created_at);
            CREATE INDEX IF NOT EXISTS idx_note_tags_note ON note_tags(note_id);
            CREATE INDEX IF NOT EXISTS idx_connections_source ON connections(source_note_id);
            CREATE INDEX IF NOT EXISTS idx_connections_target ON connections(target_note_id);
            CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions(updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);

            CREATE TABLE IF NOT EXISTS metrics (
                id SERIAL PRIMARY KEY,
                trace_id TEXT,
                metric_type TEXT NOT NULL,
                metric_name TEXT NOT NULL,
                value REAL NOT NULL,
                metadata TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_metrics_type_time ON metrics(metric_type, created_at);
            CREATE INDEX IF NOT EXISTS idx_metrics_trace ON metrics(trace_id);

            -- 用量计数器（Phase 5B 预算账本）：独立于 trace_events，可重置不破坏审计数据
            CREATE TABLE IF NOT EXISTS usage_counters (
                period_type TEXT NOT NULL,   -- today / month / total
                period_key TEXT NOT NULL,    -- 日期串如 2024-08-13（today/month），total 固定为 'all'
                tokens INTEGER NOT NULL DEFAULT 0,
                cost REAL NOT NULL DEFAULT 0,
                calls INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (period_type, period_key)
            );
        """)
        self._conn.commit()

        # trace_events 表单独创建（可能跨连接迁移）
        self._executescript(
            """
            CREATE TABLE IF NOT EXISTS trace_events (
                id SERIAL PRIMARY KEY,
                trace_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                name TEXT,
                input TEXT,
                output TEXT,
                token_usage JSONB,
                latency_ms REAL,
                run_id TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_trace_events_trace ON trace_events(trace_id, seq);
            CREATE INDEX IF NOT EXISTS idx_trace_events_trace ON trace_events(trace_id, seq);

            -- 评估分数表（Phase 5D FR55）：LLM-as-Judge 打分
            CREATE TABLE IF NOT EXISTS eval_scores (
                id SERIAL PRIMARY KEY,
                trace_id TEXT,
                question TEXT,
                answer TEXT,
                score INTEGER,
                dimensions TEXT,
                comment TEXT,
                run_id INTEGER,           -- 关联 eval_runs 批次
                judged_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_eval_scores_judged ON eval_scores(judged_at);

            -- 评估批次历史表（Phase 5D：离线评估 + Judge 抽样的运行记录）
            CREATE TABLE IF NOT EXISTS eval_runs (
                id SERIAL PRIMARY KEY,
                run_type TEXT NOT NULL,     -- 'offline' | 'judge'
                total INTEGER,
                passed INTEGER,
                pass_rate REAL,
                avg_score REAL,
                duration_ms REAL,
                details JSONB,              -- JSON 摘要
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_eval_runs_created ON eval_runs(created_at);
            """
        )
        self._conn.commit()

        # golden_cases / bad_cases 表（Phase 5D：测试集存数据库支持页面 CRUD）
        self._executescript(
            """
            CREATE TABLE IF NOT EXISTS golden_cases (
                id TEXT PRIMARY KEY,
                question TEXT NOT NULL,
                expected_keywords TEXT,
                expected_sources TEXT,
                min_score REAL DEFAULT 0.7,
                enabled INTEGER DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS bad_cases (
                id SERIAL PRIMARY KEY,
                trace_id TEXT,
                question TEXT,
                answer TEXT,
                reason TEXT,
                extra TEXT,
                collected_at TEXT NOT NULL
            );

            -- 提示词外部化（Phase 5E FR56）：配置存库 + 页面 CRUD
            CREATE TABLE IF NOT EXISTS prompts (
                prompt_key TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                content TEXT NOT NULL,
                is_template INTEGER DEFAULT 0,
                enabled INTEGER DEFAULT 1,
                version INTEGER DEFAULT 1,
                updated_at TEXT NOT NULL
            );

            -- 提示词历史版本（每次更新前归档旧内容）
            CREATE TABLE IF NOT EXISTS prompt_versions (
                id SERIAL PRIMARY KEY,
                prompt_key TEXT NOT NULL,
                version INTEGER NOT NULL,
                content TEXT NOT NULL,
                saved_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_prompt_versions_key ON prompt_versions(prompt_key, version);
            """
        )
        self._conn.commit()

        # BM25 关键词检索（Phase 5F FR58）：索引笔记标题+预览，补充向量检索的关键词命中能力
        # Postgres 用 pg_trgm GIN 索引加速 ILIKE（兼容中文，保证召回）
        self._executescript(
            """
            CREATE EXTENSION IF NOT EXISTS pg_trgm;
            CREATE INDEX IF NOT EXISTS idx_notes_title_trgm ON notes USING gin (title gin_trgm_ops);
            CREATE INDEX IF NOT EXISTS idx_notes_preview_trgm ON notes USING gin (content_preview gin_trgm_ops);
            """
        )
        self._conn.commit()

        # 表与列注释（幂等）
        self._apply_business_comments()

        # 数据库迁移：补充旧表缺失的列/表（CREATE TABLE IF NOT EXISTS 不会改已有表）
        self._migrate()

    def _apply_business_comments(self) -> None:
        """为业务元数据表和关键列添加注释（幂等）。

        这些表是系统的核心业务数据层（无表名前缀），与向量层（vec_ 前缀）、
        检查点层（checkpoint_ 前缀）区分。
        """
        statements = [
            # ---- notes: 笔记元数据 ----
            "COMMENT ON TABLE notes IS '业务层-笔记元数据：摄入的每条知识（Markdown/书签/RSS/CLI）的元信息'",
            "COMMENT ON COLUMN notes.id IS '笔记唯一 ID（UUID4）'",
            "COMMENT ON COLUMN notes.title IS '笔记标题'",
            "COMMENT ON COLUMN notes.source_type IS '来源类型：MARKDOWN / BOOKMARK / RSS / CLI'",
            "COMMENT ON COLUMN notes.source_path IS '原始文件路径或 URL'",
            "COMMENT ON COLUMN notes.file_hash IS '原始内容哈希（去重用）'",
            "COMMENT ON COLUMN notes.content_preview IS '内容预览（前 200 字，供 BM25 关键词检索）'",
            "COMMENT ON COLUMN notes.content_length IS '内容总长度（字符数）'",
            "COMMENT ON COLUMN notes.chunk_count IS '分块数量（对应 vec_note_chunks）'",
            "COMMENT ON COLUMN notes.status IS '状态：active / deleted（软删除）'",
            "COMMENT ON COLUMN notes.created_at IS '创建时间（ISO 8601）'",
            "COMMENT ON COLUMN notes.updated_at IS '最后更新时间（ISO 8601）'",
            "COMMENT ON COLUMN notes.ingested_at IS '摄入完成时间（ISO 8601）'",
            # ---- tags: 标签 ----
            "COMMENT ON TABLE tags IS '业务层-标签：笔记的分类标签，可 AI 自动或手动生成'",
            "COMMENT ON COLUMN tags.id IS '标签自增 ID'",
            "COMMENT ON COLUMN tags.name IS '标签名（唯一）'",
            "COMMENT ON COLUMN tags.category IS '标签分类：topic / type / source 等'",
            "COMMENT ON COLUMN tags.is_ai_generated IS '是否 AI 生成（0/1）'",
            # ---- note_tags: 笔记-标签关联 ----
            "COMMENT ON TABLE note_tags IS '业务层-笔记标签关联：多对多关系，带分类置信度'",
            "COMMENT ON COLUMN note_tags.note_id IS '笔记 ID'",
            "COMMENT ON COLUMN note_tags.tag_id IS '标签 ID'",
            "COMMENT ON COLUMN note_tags.confidence IS '分类置信度（0.0-1.0，AI 生成时填充）'",
            # ---- connections: 知识关联 ----
            "COMMENT ON TABLE connections IS '业务层-知识关联：笔记间的语义关联，构建知识图谱的边'",
            "COMMENT ON COLUMN connections.id IS '关联自增 ID'",
            "COMMENT ON COLUMN connections.source_note_id IS '源笔记 ID'",
            "COMMENT ON COLUMN connections.target_note_id IS '目标笔记 ID'",
            "COMMENT ON COLUMN connections.relation_type IS '关联类型：related / depends_on / extends 等'",
            "COMMENT ON COLUMN connections.strength IS '关联强度（0.0-1.0）'",
            "COMMENT ON COLUMN connections.description IS '关联描述（AI 生成）'",
            "COMMENT ON COLUMN connections.is_ai_generated IS '是否 AI 生成（0/1）'",
            # ---- sessions: 对话会话 ----
            "COMMENT ON TABLE sessions IS '业务层-对话会话：用户与 AI 的问答会话'",
            "COMMENT ON COLUMN sessions.id IS '会话唯一 ID（UUID4，等于 LangGraph thread_id）'",
            "COMMENT ON COLUMN sessions.title IS '会话标题'",
            "COMMENT ON COLUMN sessions.pending_msg_id IS 'HIL 中断时暂存的待续消息 ID（关联 messages.id）'",
            # ---- messages: 对话消息 ----
            "COMMENT ON TABLE messages IS '业务层-对话消息：会话内的单条消息（user/assistant）'",
            "COMMENT ON COLUMN messages.session_id IS '所属会话 ID'",
            "COMMENT ON COLUMN messages.role IS '消息角色：user / assistant'",
            "COMMENT ON COLUMN messages.content IS '消息内容'",
            "COMMENT ON COLUMN messages.timeline IS '工具调用轨迹（JSONB：[{kind,name,args,done}]）'",
            "COMMENT ON COLUMN messages.status IS '消息状态：complete / pending（HIL 中断态）'",
            # ---- knowledge_fragments: 知识片段 ----
            "COMMENT ON TABLE knowledge_fragments IS '业务层-知识片段：HIL 沉淀的精炼知识（用户确认后写入，喂给向量层）'",
            "COMMENT ON COLUMN knowledge_fragments.session_id IS '来源会话 ID'",
            "COMMENT ON COLUMN knowledge_fragments.status IS '审核状态：approved / rejected'",
            # ---- ingestion_log: 摄入日志 ----
            "COMMENT ON TABLE ingestion_log IS '业务层-摄入日志：记录每条笔记摄入流水线各阶段的事件和耗时'",
            "COMMENT ON COLUMN ingestion_log.event IS '事件：parse / chunk / embed / index / classify / connect'",
            "COMMENT ON COLUMN ingestion_log.status IS '状态：success / error'",
            "COMMENT ON COLUMN ingestion_log.duration_ms IS '阶段耗时（毫秒）'",
            # ---- reviews: 复习调度 ----
            "COMMENT ON TABLE reviews IS '业务层-复习调度：SM-2 间隔重复算法的复习记录'",
            "COMMENT ON COLUMN reviews.ease_factor IS 'SM-2 熟练度系数（下限 1.3）'",
            "COMMENT ON COLUMN reviews.interval_days IS '当前复习间隔（天）'",
            "COMMENT ON COLUMN reviews.due_date IS '下次复习日期（ISO）'",
            "COMMENT ON COLUMN reviews.review_count IS '已复习次数'",
            "COMMENT ON COLUMN reviews.last_quality IS '上次评分（0-5）'",
            # ---- digest_reports: 生成报告 ----
            "COMMENT ON TABLE digest_reports IS '业务层-生成报告：每日/每周知识摘要报告'",
            "COMMENT ON COLUMN digest_reports.report_type IS '报告类型：daily / weekly'",
            # ---- rss_feeds / rss_entries: RSS 订阅 ----
            "COMMENT ON TABLE rss_feeds IS '业务层-RSS 订阅源'",
            "COMMENT ON COLUMN rss_feeds.entry_count IS '已拉取条目数'",
            "COMMENT ON TABLE rss_entries IS '业务层-RSS 条目：订阅源的每篇文章'",
            "COMMENT ON COLUMN rss_entries.entry_id IS 'feed 内条目唯一 ID（去重用）'",
            "COMMENT ON COLUMN rss_entries.note_id IS '摄入后生成的笔记 ID（未摄入为空）'",
            "COMMENT ON COLUMN rss_entries.content IS '条目正文（feed content 字段或抓取网页的全文）'",
            # ---- metrics: 指标记录 ----
            "COMMENT ON TABLE metrics IS '可观测层-指标记录：数值型指标（latency/token/count），供看板聚合'",
            "COMMENT ON COLUMN metrics.metric_type IS '指标类型：ingest / ask / connect 等'",
            "COMMENT ON COLUMN metrics.metric_name IS '指标名：count / latency_ms / tokens'",
            # ---- usage_counters: 用量计数器 ----
            "COMMENT ON TABLE usage_counters IS '可观测层-用量计数器：预算账本（today/month/total），可重置不破坏审计数据'",
            "COMMENT ON COLUMN usage_counters.period_type IS '周期类型：today / month / total'",
            "COMMENT ON COLUMN usage_counters.period_key IS '周期键：日期串（today/month）或 all（total），跨期轮转'",
            "COMMENT ON COLUMN usage_counters.tokens IS '累计 token 数'",
            "COMMENT ON COLUMN usage_counters.cost IS '累计成本（元）'",
            "COMMENT ON COLUMN usage_counters.calls IS '累计调用次数'",
            # ---- trace_events: 调用链 ----
            "COMMENT ON TABLE trace_events IS '可观测层-调用链事件：LLM/工具的入参出参全量记录，供调用链回放（与 metrics 通过 trace_id 关联）'",
            "COMMENT ON COLUMN trace_events.trace_id IS '调用链 ID（关联 metrics.trace_id）'",
            "COMMENT ON COLUMN trace_events.seq IS '事件序号（同一 trace 内递增）'",
            "COMMENT ON COLUMN trace_events.event_type IS '事件类型：llm_start / llm_end / tool_start / tool_end'",
            "COMMENT ON COLUMN trace_events.token_usage IS 'token 用量明细（JSONB：含 cost）'",
            "COMMENT ON COLUMN trace_events.run_id IS '关联的评估批次 ID（eval_runs.id）'",
            # ---- eval_scores / eval_runs: 评估 ----
            "COMMENT ON TABLE eval_scores IS '评估层-LLM-as-Judge 打分：单条问答的质量评分'",
            "COMMENT ON COLUMN eval_scores.run_id IS '关联评估批次（eval_runs.id）'",
            "COMMENT ON TABLE eval_runs IS '评估层-评估批次：离线评估 + Judge 抽样的运行记录'",
            "COMMENT ON COLUMN eval_runs.run_type IS '批次类型：offline / judge'",
            "COMMENT ON COLUMN eval_runs.details IS '批次摘要（JSONB）'",
            # ---- golden_cases / bad_cases: 测试集 ----
            "COMMENT ON TABLE golden_cases IS '评估层-黄金测试集：离线评估的标准问答（可页面 CRUD）'",
            "COMMENT ON COLUMN golden_cases.expected_keywords IS '期望命中的关键词（JSON 数组字符串）'",
            "COMMENT ON COLUMN golden_cases.expected_sources IS '期望命中的笔记来源 ID（JSON 数组字符串）'",
            "COMMENT ON COLUMN golden_cases.min_score IS '最低合格分（0.0-1.0）'",
            "COMMENT ON TABLE bad_cases IS '评估层-坏案例：用户反馈“回答不好”的回流样本'",
            # ---- prompts / prompt_versions: 提示词 ----
            "COMMENT ON TABLE prompts IS '配置层-提示词：AI 提示词外部化存储（页面 CRUD，即时生效）'",
            "COMMENT ON COLUMN prompts.prompt_key IS '提示词唯一键（如 classifier / connector）'",
            "COMMENT ON COLUMN prompts.is_template IS '是否含占位符模板（1=需 str.format 渲染）'",
            "COMMENT ON TABLE prompt_versions IS '配置层-提示词历史版本：每次更新前归档旧内容，支持回滚'",
        ]
        for stmt in statements:
            try:
                self._conn.cursor().execute(stmt)
            except Exception:
                pass  # 注释失败不阻塞建表流程
        self._conn.commit()

    def _migrate(self) -> None:
        """增量迁移：为旧数据库补充新增的列和表。"""
        assert self._conn is not None

        def has_column(table: str, column: str) -> bool:
            cur = self._exec(
                "SELECT COUNT(*) AS cnt FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name=%s AND column_name=%s",
                (table, column),
            )
            row = cur.fetchone()
            return (row["cnt"] if row else 0) > 0

        def has_table(table: str) -> bool:
            cur = self._exec(
                "SELECT COUNT(*) AS cnt FROM information_schema.tables "
                "WHERE table_schema = current_schema() AND table_name=%s",
                (table,),
            )
            row = cur.fetchone()
            return (row["cnt"] if row else 0) > 0

        # messages 表补 status 列（HIL 中断态标记：complete/pending）
        if has_table("messages") and not has_column("messages", "status"):
            self._exec(
                "ALTER TABLE messages ADD COLUMN status TEXT NOT NULL DEFAULT 'complete'"
            )
            logger.info("迁移: messages 表新增 status 列")

        # sessions 表补 pending_msg_id 列（HIL 中断时暂存待续消息 id）
        if has_table("sessions") and not has_column("sessions", "pending_msg_id"):
            self._exec("ALTER TABLE sessions ADD COLUMN pending_msg_id INTEGER")
            logger.info("迁移: sessions 表新增 pending_msg_id 列")

        # eval_scores 补 run_id 列（Phase 5D 评估批次关联）
        if has_table("eval_scores") and not has_column("eval_scores", "run_id"):
            self._exec("ALTER TABLE eval_scores ADD COLUMN run_id INTEGER")
            logger.info("迁移: eval_scores 表新增 run_id 列")

        # rss_entries 表补 content 列（存条目正文）
        if has_table("rss_entries") and not has_column("rss_entries", "content"):
            self._exec("ALTER TABLE rss_entries ADD COLUMN content TEXT DEFAULT ''")
            logger.info("迁移: rss_entries 表新增 content 列")

        # eval_runs 表（旧库可能没有）
        if not has_table("eval_runs"):
            self._executescript(
                """
                CREATE TABLE IF NOT EXISTS eval_runs (
                    id SERIAL PRIMARY KEY,
                    run_type TEXT NOT NULL,
                    total INTEGER,
                    passed INTEGER,
                    pass_rate REAL,
                    avg_score REAL,
                    duration_ms REAL,
                    details JSONB,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_eval_runs_created ON eval_runs(created_at);
                """
            )
            logger.info("迁移: 新建 eval_runs 表")

        # 回填 usage_counters（从 trace_events 历史数据初始化计数器）
        self._backfill_usage_counters()

        # 播种提示词（Phase 5E：首次初始化写入 6 条默认值）
        self._seed_prompts()

        # BM25 全文索引初始化（Phase 5F FR58）
        self._init_bm25_index()

        self._conn.commit()

    def _init_bm25_index(self) -> None:
        """初始化 BM25 关键词检索索引（Phase 5F FR58）。

        Postgres 用 pg_trgm GIN 索引加速 ILIKE（在 _create_tables 已创建），
        此方法保留为空操作（索引随表创建，无需额外回填）。
        """

    def _sync_fts_note(
        self, note_id: str, title: str, content_preview: str,
        insert: bool = True, delete_only: bool = False,
    ) -> None:
        """同步单条笔记到 BM25 索引。

        Postgres 的 pg_trgm 索引直接挂在 notes 表，写入即同步，此方法为空操作。
        保留签名以兼容调用方（add_note/update_note/delete_note）。
        """

    @_synchronized
    def bm25_search(self, query: str, top_k: int = 20) -> list[dict]:
        """关键词检索（Phase 5F FR58）。

        索引笔记标题 + content_preview，返回 note_id + score + title + preview。
        Postgres 用 ILIKE + pg_trgm GIN 索引（兼容中文，按相似度排序）。

        Args:
            query: 搜索查询（自然语言或关键词）
            top_k: 返回结果数

        Returns:
            [{note_id, score, title, content_preview}, ...]，按相似度降序
        """
        assert self._conn is not None
        if not query.strip():
            return []
        try:
            rows = self._like_query(query, top_k)
            return [
                {
                    "note_id": r["id"],
                    "score": round(float(r["score"]), 4) if r["score"] is not None else 0.0,
                    "title": r["title"] or "",
                    "content_preview": r["content_preview"] or "",
                }
                for r in rows
            ]
        except Exception as e:
            logger.warning(f"BM25 检索失败（降级为空结果）: {e}")
            return []

    def _like_query(self, query: str, top_k: int) -> list:
        """ILIKE 模糊查询（pg_trgm GIN 索引加速，兼容中文短语）。

        similarity() 给出 0-1 的相似度分用于排序。
        """
        pattern = f"%{query}%"
        return self._exec(
            """SELECT id, title, content_preview,
                      similarity(title || ' ' || content_preview, %s) as score
               FROM notes
               WHERE status = 'active'
                 AND (title ILIKE %s OR content_preview ILIKE %s)
               ORDER BY score DESC
               LIMIT %s""",
            (query, pattern, pattern, top_k),
        ).fetchall()


    def _backfill_usage_counters(self) -> None:
        """从 trace_events 历史数据回填 usage_counters 计数器。

        幂等：仅在 usage_counters 为空时执行（避免重复累加）。
        将历史 llm_end 事件按 today/month/total 三个周期初始化计数器。
        """
        from datetime import datetime

        # 已有计数器数据则跳过
        row = self._exec(
            "SELECT COUNT(*) as cnt FROM usage_counters"
        ).fetchone()
        if row and row["cnt"] > 0:
            return

        # 从 trace_events 按日期聚合历史 token/cost
        rows = self._exec(
            """SELECT substr(created_at, 1, 10) as day,
                      substr(created_at, 1, 7) as month,
                      COALESCE(json_extract(token_usage, '$.total'), 0) as tokens,
                      COALESCE(json_extract(token_usage, '$.cost'), 0) as cost
               FROM trace_events
               WHERE event_type='llm_end' AND token_usage IS NOT NULL"""
        ).fetchall()
        if not rows:
            return

        now_key = datetime.now().strftime("%Y-%m-%d")
        now_month = datetime.now().strftime("%Y-%m")
        today_tokens = today_cost = 0
        month_tokens = month_cost = 0
        total_tokens = total_cost = 0

        for r in rows:
            tokens = int(r["tokens"] or 0)
            cost = float(r["cost"] or 0)
            total_tokens += tokens
            total_cost += cost
            if r["day"] == now_key:
                today_tokens += tokens
                today_cost += cost
            if r["month"] == now_month:
                month_tokens += tokens
                month_cost += cost

        now_iso = datetime.now().isoformat()
        for pt, pk, t, c in [
            ("today", now_key, today_tokens, today_cost),
            ("month", now_month, month_tokens, month_cost),
            ("total", "all", total_tokens, total_cost),
        ]:
            self._exec(
                """INSERT INTO usage_counters
                   (period_type, period_key, tokens, cost, calls, updated_at)
                   VALUES (?, ?, ?, ?, 0, ?)
                   ON CONFLICT (period_type) DO UPDATE SET
                       period_key = EXCLUDED.period_key,
                       tokens = EXCLUDED.tokens,
                       cost = EXCLUDED.cost,
                       calls = EXCLUDED.calls,
                       updated_at = EXCLUDED.updated_at""",
                (pt, pk, t, round(c, 6), now_iso),
            )
        logger.info(
            f"回填 usage_counters: today={today_tokens}t/¥{today_cost:.4f}, "
            f"month={month_tokens}t/¥{month_cost:.4f}, total={total_tokens}t/¥{total_cost:.4f}"
        )

    def _seed_prompts(self) -> None:
        """写入默认提示词（幂等）。

        - 空表：写入全部默认值
        - 已有数据：补充缺失的 key（如旧库升级时新增的 query_rewriter）
        """
        from datetime import datetime

        from brain.storage.prompt_defaults import DEFAULT_PROMPTS

        now_iso = datetime.now().isoformat()
        row = self._exec("SELECT COUNT(*) as cnt FROM prompts").fetchone()
        is_empty = not (row and row["cnt"] > 0)

        if is_empty:
            for key, name, desc, content, is_template in DEFAULT_PROMPTS:
                self._exec(
                    """INSERT INTO prompts
                       (prompt_key, name, description, content, is_template, enabled, version, updated_at)
                       VALUES (?, ?, ?, ?, ?, 1, 1, ?)
                       ON CONFLICT (prompt_key) DO NOTHING""",
                    (key, name, desc, content, is_template, now_iso),
                )
            logger.info(f"播种提示词: {len(DEFAULT_PROMPTS)} 条默认值")
        else:
            # 旧库升级：补充 5E 之后新增的提示词（如 5F 的 query_rewriter）
            added = 0
            for key, name, desc, content, is_template in DEFAULT_PROMPTS:
                existing = self._exec(
                    "SELECT prompt_key FROM prompts WHERE prompt_key = ?", (key,)
                ).fetchone()
                if existing is None:
                    self._exec(
                        """INSERT INTO prompts
                           (prompt_key, name, description, content, is_template, enabled, version, updated_at)
                           VALUES (?, ?, ?, ?, ?, 1, 1, ?)
                           ON CONFLICT (prompt_key) DO NOTHING""",
                        (key, name, desc, content, is_template, now_iso),
                    )
                    added += 1
                    logger.info(f"补充提示词: {key}")
            if added:
                logger.info(f"提示词升级：补充 {added} 条新增默认值")

    # ---- Notes CRUD ----

    @_synchronized
    def create_note(self, note: NoteMetadata) -> str:
        assert self._conn is not None
        self._exec(
            """INSERT INTO notes (id, title, source_type, source_path, file_hash,
               content_preview, content_length, chunk_count, status,
               created_at, updated_at, ingested_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                note.id, note.title, note.source_type.value, note.source_path,
                note.file_hash, note.content_preview, note.content_length,
                note.chunk_count, note.status.value, note.created_at,
                note.updated_at, note.ingested_at,
            ),
        )
        # 同步 BM25 索引（Phase 5F）
        self._sync_fts_note(note.id, note.title, note.content_preview, insert=True)
        self._conn.commit()
        logger.debug(f"MetadataStore: 已创建笔记 {note.id} — {note.title}")
        return note.id

    @_synchronized
    def get_note(self, note_id: str) -> NoteMetadata | None:
        assert self._conn is not None
        row = self._exec("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
        if row is None:
            return None
        return self._row_to_note(row)

    @_synchronized
    def list_notes(
        self, status: NoteStatus = NoteStatus.ACTIVE, limit: int = 50, offset: int = 0,
    ) -> list[NoteMetadata]:
        assert self._conn is not None
        rows = self._exec(
            "SELECT * FROM notes WHERE status = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (status.value, limit, offset),
        ).fetchall()
        return [self._row_to_note(r) for r in rows]

    @_synchronized
    def update_note(self, note_id: str, **kwargs) -> None:
        assert self._conn is not None
        allowed = {"title", "content_preview", "content_length", "chunk_count",
                    "status", "file_hash", "updated_at", "ingested_at"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [note_id]
        self._exec(f"UPDATE notes SET {set_clause} WHERE id = ?", values)
        # 同步 BM25 索引（标题/预览变更时重建该行 FTS）
        if "title" in updates or "content_preview" in updates:
            row = self._exec(
                "SELECT title, content_preview FROM notes WHERE id = ?", (note_id,)
            ).fetchone()
            if row:
                self._sync_fts_note(note_id, row["title"], row["content_preview"], insert=False)
        self._conn.commit()

    @_synchronized
    def delete_note(self, note_id: str, soft: bool = True) -> None:
        assert self._conn is not None
        if soft:
            self._exec("UPDATE notes SET status = ? WHERE id = ?",
                               (NoteStatus.DELETED.value, note_id))
        else:
            self._exec("DELETE FROM notes WHERE id = ?", (note_id,))
            # 硬删除时同步移除 BM25 索引（软删除保留，BM25 检索时按 status 过滤）
            self._sync_fts_note(note_id, "", "", insert=False, delete_only=True)
        self._conn.commit()
        logger.info(f"MetadataStore: 已{'软' if soft else '硬'}删除笔记 {note_id}")

    @_synchronized
    def note_exists(self, file_hash: str) -> str | None:
        assert self._conn is not None
        row = self._exec(
            "SELECT id FROM notes WHERE file_hash = ? AND status = 'active'",
            (file_hash,),
        ).fetchone()
        return row["id"] if row else None

    @_synchronized
    def count_notes(self, status: NoteStatus = NoteStatus.ACTIVE) -> int:
        assert self._conn is not None
        row = self._exec(
            "SELECT COUNT(*) as cnt FROM notes WHERE status = ?", (status.value,),
        ).fetchone()
        return row["cnt"] if row else 0

    # ---- Tags ----

    @_synchronized
    def get_or_create_tag(self, name: str, category: TagCategory, is_ai: bool = False) -> int:
        assert self._conn is not None
        row = self._exec("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()
        if row:
            return row["id"]
        cur = self._exec(
            "INSERT INTO tags (name, category, is_ai_generated) VALUES (?, ?, ?) RETURNING id",
            (name, category.value, int(is_ai)),
        )
        self._conn.commit()
        return cur.fetchone()["id"]

    @_synchronized
    def add_tag_to_note(self, note_id: str, tag_id: int, confidence: float | None = None) -> None:
        assert self._conn is not None
        self._exec(
            """INSERT INTO note_tags (note_id, tag_id, confidence) VALUES (?, ?, ?)
                   ON CONFLICT (note_id, tag_id) DO UPDATE SET confidence = EXCLUDED.confidence""",
            (note_id, tag_id, confidence),
        )
        self._conn.commit()

    @_synchronized
    def get_note_tags(self, note_id: str) -> list[Tag]:
        assert self._conn is not None
        rows = self._exec(
            """SELECT t.id, t.name, t.category, t.is_ai_generated, nt.confidence
               FROM tags t
               JOIN note_tags nt ON t.id = nt.tag_id
               WHERE nt.note_id = ?
               ORDER BY t.category, t.name""",
            (note_id,),
        ).fetchall()
        return [
            Tag(
                id=row["id"], name=row["name"],
                category=TagCategory(row["category"]) if row["category"] else TagCategory.TOPIC,
                is_ai_generated=bool(row["is_ai_generated"]),
                confidence=row["confidence"],
            ) for row in rows
        ]

    @_synchronized
    def remove_tag_from_note(self, note_id: str, tag_name: str) -> bool:
        """按标签名从笔记移除标签关联（Phase 4B FR36）。

        需先查 tag_id 再删 note_tags 关联（不删 tags 表本身，保留标签定义）。
        返回是否删除成功。
        """
        assert self._conn is not None
        # 先查 tag_id（标签名唯一）
        row = self._exec("SELECT id FROM tags WHERE name = ?", (tag_name,)).fetchone()
        if row is None:
            return False
        tag_id = row["id"]
        cur = self._exec(
            "DELETE FROM note_tags WHERE note_id = ? AND tag_id = ?",
            (note_id, tag_id),
        )
        self._conn.commit()
        deleted = cur.rowcount > 0
        if deleted:
            logger.info(f"MetadataStore: 已从笔记 {note_id} 移除标签 {tag_name}")
        return deleted

    # ---- Connections ----

    @_synchronized
    def add_connection(self, conn: Connection) -> int:
        assert self._conn is not None
        cur = self._exec(
            """INSERT INTO connections
               (source_note_id, target_note_id, relation_type, strength,
                description, created_at, is_ai_generated)
               VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING id""",
            (conn.source_note_id, conn.target_note_id, conn.relation_type.value,
             conn.strength, conn.description, conn.created_at, int(conn.is_ai_generated)),
        )
        self._conn.commit()
        return cur.fetchone()["id"]

    @_synchronized
    def get_connections(self, note_id: str) -> list[Connection]:
        assert self._conn is not None
        rows = self._exec(
            """SELECT * FROM connections
               WHERE source_note_id = ? OR target_note_id = ?
               ORDER BY strength DESC""",
            (note_id, note_id),
        ).fetchall()
        return [self._row_to_connection(r) for r in rows]

    @_synchronized
    def delete_connection(self, conn_id: int) -> bool:
        """按关联 ID 删除（Phase 4B FR36）。返回是否删除成功。"""
        assert self._conn is not None
        cur = self._exec("DELETE FROM connections WHERE id = ?", (conn_id,))
        self._conn.commit()
        deleted = cur.rowcount > 0
        if deleted:
            logger.info(f"MetadataStore: 已删除关联 {conn_id}")
        return deleted

    # ---- Ingestion Log ----

    @_synchronized
    def log_event(self, note_id: str, event: str, status: str,
                  message: str = "", duration_ms: int | None = None) -> None:
        assert self._conn is not None
        self._exec(
            """INSERT INTO ingestion_log (note_id, event, status, message, duration_ms, timestamp)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (note_id, event, status, message, duration_ms, datetime.now().isoformat()),
        )
        self._conn.commit()

    # ---- Sessions（会话） ----

    @_synchronized
    def create_session(self, session_id: str, title: str = "新对话") -> str:
        """创建会话。返回 session_id。"""
        assert self._conn is not None
        now = datetime.now().isoformat()
        self._exec(
            "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (session_id, title, now, now),
        )
        self._conn.commit()
        return session_id

    @_synchronized
    def list_sessions(self, limit: int = 50) -> list[dict]:
        """列出会话（按最近更新排序）。"""
        assert self._conn is not None
        rows = self._exec(
            "SELECT id, title, created_at, updated_at FROM sessions ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            {
                "id": r["id"],
                "title": r["title"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]

    @_synchronized
    def get_session(self, session_id: str) -> dict | None:
        """获取会话详情。"""
        assert self._conn is not None
        row = self._exec(
            "SELECT id, title, created_at, updated_at FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "title": row["title"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @_synchronized
    def rename_session(self, session_id: str, title: str) -> None:
        """重命名会话并刷新 updated_at。"""
        assert self._conn is not None
        self._exec(
            "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?",
            (title, datetime.now().isoformat(), session_id),
        )
        self._conn.commit()

    @_synchronized
    def touch_session(self, session_id: str) -> None:
        """刷新会话的 updated_at（有新消息时调用）。"""
        assert self._conn is not None
        self._exec(
            "UPDATE sessions SET updated_at = ? WHERE id = ?",
            (datetime.now().isoformat(), session_id),
        )
        self._conn.commit()

    @_synchronized
    def delete_session(self, session_id: str) -> None:
        """删除会话（消息级联删除）。"""
        assert self._conn is not None
        self._exec("DELETE FROM sessions WHERE id = ?", (session_id,))
        self._conn.commit()

    # ---- Messages（会话消息） ----

    @_synchronized
    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        timeline: list | None = None,
        status: str = "complete",
    ) -> int:
        """保存一条消息。返回消息 ID。

        Args:
            status: 'complete'（默认）或 'pending'（HIL 中断时的待续消息）
        """
        assert self._conn is not None
        import json

        timeline_json = json.dumps(timeline or [], ensure_ascii=False)
        cur = self._exec(
            """INSERT INTO messages (session_id, role, content, timeline, created_at, status)
               VALUES (?, ?, ?, ?, ?, ?) RETURNING id""",
            (session_id, role, content, timeline_json, datetime.now().isoformat(), status),
        )
        self._conn.commit()
        return cur.fetchone()["id"]

    @_synchronized
    def update_message(
        self,
        msg_id: int,
        content: str,
        timeline: list | None = None,
        status: str = "complete",
    ) -> bool:
        """更新一条消息的 content/timeline/status（HIL resume 合并待续消息用）。"""
        assert self._conn is not None
        import json

        timeline_json = json.dumps(timeline or [], ensure_ascii=False)
        cur = self._exec(
            """UPDATE messages SET content = ?, timeline = ?, status = ?
               WHERE id = ?""",
            (content, timeline_json, status, msg_id),
        )
        self._conn.commit()
        return cur.rowcount > 0

    @_synchronized
    def get_pending_msg_id(self, session_id: str) -> int | None:
        """获取会话的待续消息 ID（HIL 中断态标记）。None 表示无中断。"""
        assert self._conn is not None
        row = self._exec(
            "SELECT pending_msg_id FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        return row["pending_msg_id"] if row else None

    @_synchronized
    def set_pending_msg_id(self, session_id: str, msg_id: int | None) -> None:
        """设置/清空会话的待续消息 ID（None=清空）。"""
        assert self._conn is not None
        self._exec(
            "UPDATE sessions SET pending_msg_id = ? WHERE id = ?",
            (msg_id, session_id),
        )
        self._conn.commit()

    @_synchronized
    def get_messages(self, session_id: str) -> list[dict]:
        """获取会话的全部消息（按时间正序）。"""
        assert self._conn is not None
        import json

        rows = self._exec(
            "SELECT id, role, content, timeline, created_at, status FROM messages WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
        result = []
        for r in rows:
            # timeline 是 JSONB，psycopg 自动解析为 list；旧数据可能为 None/字符串
            tl = r["timeline"]
            if tl is None:
                timeline = []
            elif isinstance(tl, str):
                try:
                    timeline = json.loads(tl)
                except json.JSONDecodeError:
                    timeline = []
            else:
                timeline = tl  # 已是 list
            result.append(
                {
                    "id": r["id"],
                    "role": r["role"],
                    "content": r["content"],
                    "timeline": timeline,
                    "created_at": r["created_at"],
                    "status": r["status"],
                }
            )
        return result

    @_synchronized
    def count_messages(self, session_id: str) -> int:
        """会话消息数。"""
        assert self._conn is not None
        row = self._exec(
            "SELECT COUNT(*) as cnt FROM messages WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return row["cnt"] if row else 0

    # ---- Knowledge Fragments（知识片段，HIL 确认后保存） ----

    @_synchronized
    def add_knowledge_fragment(
        self,
        title: str,
        content: str,
        session_id: str | None = None,
        status: str = "approved",
    ) -> int:
        """保存一条知识片段。返回片段 ID。"""
        assert self._conn is not None
        cur = self._exec(
            """INSERT INTO knowledge_fragments (session_id, title, content, status, created_at)
               VALUES (?, ?, ?, ?, ?) RETURNING id""",
            (session_id, title, content, status, datetime.now().isoformat()),
        )
        self._conn.commit()
        logger.info(f"MetadataStore: 知识片段已保存 — {title}")
        return cur.fetchone()["id"]

    @_synchronized
    def list_knowledge_fragments(self, limit: int = 50) -> list[dict]:
        """列出知识片段（按时间倒序）。"""
        assert self._conn is not None
        rows = self._exec(
            """SELECT id, session_id, title, content, status, created_at
               FROM knowledge_fragments
               ORDER BY id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [
            {
                "id": r["id"],
                "session_id": r["session_id"],
                "title": r["title"],
                "content": r["content"],
                "status": r["status"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    @_synchronized
    def find_similar_fragment(self, title: str) -> dict | None:
        """按标题查找已有知识片段（子智能体去重用）。"""
        assert self._conn is not None
        row = self._exec(
            "SELECT id, title, content FROM knowledge_fragments WHERE title = ? LIMIT 1",
            (title,),
        ).fetchone()
        if row is None:
            return None
        return {"id": row["id"], "title": row["title"], "content": row["content"]}

    @_synchronized
    def delete_knowledge_fragment(self, fragment_id: int) -> bool:
        """删除知识片段。返回是否删除成功。"""
        assert self._conn is not None
        cur = self._exec(
            "DELETE FROM knowledge_fragments WHERE id = ?", (fragment_id,)
        )
        self._conn.commit()
        return cur.rowcount > 0

    @_synchronized
    def search_knowledge_fragments(self, keyword: str, limit: int = 10) -> list[dict]:
        """按关键词模糊搜索知识片段（标题和内容）。"""
        assert self._conn is not None
        pattern = f"%{keyword}%"
        rows = self._exec(
            """SELECT id, session_id, title, content, status, created_at
               FROM knowledge_fragments
               WHERE title LIKE ? OR content LIKE ?
               ORDER BY id DESC LIMIT ?""",
            (pattern, pattern, limit),
        ).fetchall()
        return [
            {
                "id": r["id"],
                "session_id": r["session_id"],
                "title": r["title"],
                "content": r["content"],
                "status": r["status"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    # ---- Digest Reports（定时任务生成的摘要报告） ----

    @_synchronized
    def save_digest_report(self, report_type: str, report_date: str, content: str) -> int:
        """保存摘要报告（同类型同日期覆盖）。"""
        assert self._conn is not None
        cur = self._exec(
            """INSERT INTO digest_reports (report_type, report_date, content, created_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(report_type, report_date) DO UPDATE SET
                 content = excluded.content,
                 created_at = excluded.created_at RETURNING id""",
            (report_type, report_date, content, datetime.now().isoformat()),
        )
        self._conn.commit()
        return cur.fetchone()["id"]

    @_synchronized
    def get_digest_report(self, report_type: str, report_date: str) -> dict | None:
        """按类型和日期获取摘要报告。"""
        assert self._conn is not None
        row = self._exec(
            "SELECT id, report_type, report_date, content, created_at FROM digest_reports WHERE report_type = ? AND report_date = ?",
            (report_type, report_date),
        ).fetchone()
        return dict(row) if row else None

    @_synchronized
    def list_digest_reports(self, limit: int = 10) -> list[dict]:
        """列出最近摘要报告。"""
        assert self._conn is not None
        rows = self._exec(
            "SELECT id, report_type, report_date, content, created_at FROM digest_reports ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ---- Reviews（SM-2 间隔重复） ----

    @_synchronized
    def get_review(self, note_id: str) -> dict | None:
        """获取笔记的复习状态。"""
        assert self._conn is not None
        row = self._exec(
            "SELECT * FROM reviews WHERE note_id = ?", (note_id,)
        ).fetchone()
        return dict(row) if row else None

    @_synchronized
    def upsert_review(
        self,
        note_id: str,
        ease_factor: float,
        interval_days: int,
        due_date: str,
        review_count: int,
        last_quality: int,
    ) -> None:
        """写入/更新复习状态（SM-2 计算后的结果）。"""
        assert self._conn is not None
        now = datetime.now().isoformat()
        self._exec(
            """INSERT INTO reviews
               (note_id, ease_factor, interval_days, due_date, review_count, last_quality, last_reviewed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(note_id) DO UPDATE SET
                 ease_factor = excluded.ease_factor,
                 interval_days = excluded.interval_days,
                 due_date = excluded.due_date,
                 review_count = excluded.review_count,
                 last_quality = excluded.last_quality,
                 last_reviewed_at = excluded.last_reviewed_at""",
            (note_id, ease_factor, interval_days, due_date, review_count, last_quality, now),
        )
        self._conn.commit()

    @_synchronized
    def get_due_reviews(self, limit: int = 50) -> list[dict]:
        """一次 SQL 取全部到期复习（含笔记标题）。"""
        assert self._conn is not None
        today = date.today().isoformat()
        rows = self._exec(
            """SELECT r.*, n.title, n.ingested_at
               FROM reviews r
               JOIN notes n ON n.id = r.note_id
               WHERE n.status = 'active' AND r.due_date <= ?
               ORDER BY r.due_date ASC LIMIT ?""",
            (today, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    @_synchronized
    def get_review_candidates(self, limit: int = 10) -> list[dict]:
        """从未进入复习系统的笔记（首次复习候选）。"""
        assert self._conn is not None
        rows = self._exec(
            """SELECT n.id AS note_id, n.title, n.ingested_at, n.content_preview
               FROM notes n
               LEFT JOIN reviews r ON r.note_id = n.id
               WHERE n.status = 'active' AND r.note_id IS NULL
               ORDER BY n.ingested_at ASC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    # ---- 批量查询（避免 N+1 全表扫描） ----

    @_synchronized
    def list_notes_by_tag(self, tag_name: str, limit: int = 50) -> list[NoteMetadata]:
        """按标签名（模糊匹配）一次 SQL 查出全部笔记。

        替代"list_notes 全表 + 每篇再查标签"的 N+1 模式。
        """
        assert self._conn is not None
        pattern = f"%{tag_name}%"
        rows = self._exec(
            """SELECT DISTINCT n.* FROM notes n
               JOIN note_tags nt ON n.id = nt.note_id
               JOIN tags t ON t.id = nt.tag_id
               WHERE n.status = 'active' AND t.name LIKE ?
               ORDER BY n.created_at DESC LIMIT ?""",
            (pattern, limit),
        ).fetchall()
        return [self._row_to_note(r) for r in rows]

    @_synchronized
    def get_tags_batch(self, note_ids: list[str]) -> dict[str, list[Tag]]:
        """一次 SQL 批量取多篇笔记的标签。

        Returns:
            {note_id: [Tag, ...]}——无标签的笔记不出现在键中
        """
        assert self._conn is not None
        if not note_ids:
            return {}

        placeholders = ",".join("?" for _ in note_ids)
        rows = self._exec(
            f"""SELECT nt.note_id, t.id, t.name, t.category, t.is_ai_generated, nt.confidence
               FROM note_tags nt
               JOIN tags t ON t.id = nt.tag_id
               WHERE nt.note_id IN ({placeholders})
               ORDER BY t.category, t.name""",
            note_ids,
        ).fetchall()

        result: dict[str, list[Tag]] = {}
        for row in rows:
            tag = Tag(
                id=row["id"],
                name=row["name"],
                category=TagCategory(row["category"]) if row["category"] else TagCategory.TOPIC,
                is_ai_generated=bool(row["is_ai_generated"]),
                confidence=row["confidence"],
            )
            result.setdefault(row["note_id"], []).append(tag)
        return result

    @_synchronized
    def get_tag_counts(self) -> dict[str, int]:
        """一次 SQL 统计全部标签使用次数。"""
        assert self._conn is not None
        rows = self._exec(
            """SELECT t.name, COUNT(*) as cnt
               FROM note_tags nt
               JOIN tags t ON t.id = nt.tag_id
               GROUP BY t.name"""
        ).fetchall()
        return {r["name"]: r["cnt"] for r in rows}

    @_synchronized
    def list_all_tags(self) -> list[dict]:
        """列出全部标签及使用次数（Phase 4B FR35）。

        一次 SQL JOIN 聚合，返回 [{name, category, count}]，按 count 降序。
        包含未被任何笔记使用的标签（count=0），便于管理。
        """
        assert self._conn is not None
        rows = self._exec(
            """SELECT t.name, t.category,
                      COUNT(nt.note_id) as count
               FROM tags t
               LEFT JOIN note_tags nt ON nt.tag_id = t.id
               GROUP BY t.id, t.name, t.category
               ORDER BY count DESC, t.name"""
        ).fetchall()
        return [
            {
                "name": r["name"],
                "category": r["category"] or "topic",
                "count": r["count"],
            }
            for r in rows
        ]

    @_synchronized
    def get_all_connections_flat(self) -> list[dict]:
        """一次 SQL 取全部关联（含两端笔记标题）。"""
        assert self._conn is not None
        rows = self._exec(
            """SELECT c.source_note_id, c.target_note_id, c.relation_type,
                      c.strength, c.description,
                      n1.title AS source_title, n2.title AS target_title
               FROM connections c
               JOIN notes n1 ON n1.id = c.source_note_id
               JOIN notes n2 ON n2.id = c.target_note_id
               ORDER BY c.strength DESC"""
        ).fetchall()
        return [
            {
                "source": r["source_note_id"],
                "target": r["target_note_id"],
                "relation_type": r["relation_type"],
                "strength": r["strength"],
                "description": r["description"] or "",
                "source_title": r["source_title"],
                "target_title": r["target_title"],
            }
            for r in rows
        ]

    @_synchronized
    def get_note_degree_map(self) -> dict[str, int]:
        """一次 SQL 统计每篇笔记的关联数（度数）。"""
        assert self._conn is not None
        rows = self._exec(
            """SELECT note_id, COUNT(*) as degree FROM (
                 SELECT source_note_id AS note_id FROM connections
                 UNION ALL
                 SELECT target_note_id FROM connections
               ) AS all_notes GROUP BY note_id"""
        ).fetchall()
        return {r["note_id"]: r["degree"] for r in rows}

    # ---- RSS Feeds ----

    @_synchronized
    def add_rss_feed(self, url: str) -> int:
        """添加 RSS 源。返回 feed_id。"""
        assert self._conn is not None
        cur = self._exec(
            "INSERT INTO rss_feeds (url, created_at) VALUES (?, ?) RETURNING id",
            (url, datetime.now().isoformat()),
        )
        self._conn.commit()
        return cur.fetchone()["id"]

    @_synchronized
    def list_rss_feeds(self) -> list[dict]:
        """列出全部 RSS 源。"""
        assert self._conn is not None
        rows = self._exec(
            "SELECT id, url, title, created_at, last_fetched_at, entry_count FROM rss_feeds ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]

    @_synchronized
    def get_rss_feed(self, feed_id: int) -> dict | None:
        """获取单个 RSS 源。"""
        assert self._conn is not None
        row = self._exec(
            "SELECT id, url, title, created_at, last_fetched_at, entry_count FROM rss_feeds WHERE id = ?",
            (feed_id,),
        ).fetchone()
        return dict(row) if row else None

    @_synchronized
    def delete_rss_feed(self, feed_id: int) -> bool:
        """删除 RSS 源（条目级联删除）。"""
        assert self._conn is not None
        cur = self._exec("DELETE FROM rss_feeds WHERE id = ?", (feed_id,))
        self._conn.commit()
        return cur.rowcount > 0

    @_synchronized
    def update_rss_feed_after_fetch(
        self,
        feed_id: int,
        title: str,
        new_entries: int,
    ) -> None:
        """拉取后更新源信息。"""
        assert self._conn is not None
        now = datetime.now().isoformat()
        self._exec(
            "UPDATE rss_feeds SET title = ?, last_fetched_at = ?, entry_count = entry_count + ? WHERE id = ?",
            (title, now, new_entries, feed_id),
        )
        self._conn.commit()

    @_synchronized
    def rss_entry_exists(self, feed_id: int, entry_id: str) -> bool:
        """检查 feed 条目是否已处理过。"""
        assert self._conn is not None
        row = self._exec(
            "SELECT 1 FROM rss_entries WHERE feed_id = ? AND entry_id = ?",
            (feed_id, entry_id),
        ).fetchone()
        return row is not None

    @_synchronized
    def get_rss_entry_content(self, feed_id: int, entry_id: str) -> str | None:
        """取已存条目的 content（用于判断是否需要回填正文）。不存在返回 None。"""
        assert self._conn is not None
        row = self._exec(
            "SELECT content FROM rss_entries WHERE feed_id = ? AND entry_id = ?",
            (feed_id, entry_id),
        ).fetchone()
        return row["content"] if row else None

    @_synchronized
    def update_rss_entry_content(self, feed_id: int, entry_id: str, content: str) -> None:
        """回填条目正文（已存在但 content 为空时补充）。"""
        assert self._conn is not None
        self._exec(
            "UPDATE rss_entries SET content = ? WHERE feed_id = ? AND entry_id = ?",
            (content, feed_id, entry_id),
        )
        self._conn.commit()

    @_synchronized
    def add_rss_entry(
        self,
        feed_id: int,
        entry_id: str,
        title: str,
        link: str,
        published: str,
        note_id: str = "",
        content: str = "",
    ) -> int:
        """记录一条已处理的 feed 条目（含正文）。"""
        assert self._conn is not None
        cur = self._exec(
            """INSERT INTO rss_entries (feed_id, entry_id, title, link, note_id, published_at, content)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT (feed_id, entry_id) DO NOTHING RETURNING id""",
            (feed_id, entry_id, title, link, note_id, published, content),
        )
        self._conn.commit()
        return cur.fetchone()["id"]

    @_synchronized
    def list_rss_entries(self, feed_id: int, limit: int = 50) -> list[dict]:
        """列出某订阅源的条目（含正文，按发布时间倒序）。"""
        assert self._conn is not None
        rows = self._exec(
            """SELECT id, entry_id, title, link, note_id, published_at, content
               FROM rss_entries WHERE feed_id = ?
               ORDER BY published_at DESC NULLS LAST, id DESC LIMIT ?""",
            (feed_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # ---- Metrics（可观测性指标采集，Phase 5A） ----

    @_synchronized
    def record_metric(
        self,
        metric_type: str,
        metric_name: str,
        value: float,
        trace_id: str | None = None,
        metadata: dict | None = None,
    ) -> int:
        """记录一条指标。返回指标 ID。

        Args:
            metric_type: 'ask' | 'ingest' | 'tool_call' | 'llm_call'
            metric_name: 'latency_ms' | 'token_count' | 'count' 等
            value: 指标值
            trace_id: 关联的问答 trace_id（ingest 类指标可为 None）
            metadata: 附加信息 {model, tool_name, status, ...}
        """
        assert self._conn is not None
        import json

        meta_json = json.dumps(metadata, ensure_ascii=False) if metadata else None
        cur = self._exec(
            """INSERT INTO metrics (trace_id, metric_type, metric_name, value, metadata, created_at)
               VALUES (?, ?, ?, ?, ?, ?) RETURNING id""",
            (trace_id, metric_type, metric_name, value, meta_json, datetime.now().isoformat()),
        )
        self._conn.commit()
        return cur.fetchone()["id"]

    @_synchronized
    def get_metrics_summary(self, hours: int = 24) -> dict:
        """获取最近 N 小时的指标汇总（看板用）。

        Returns:
            {
                "ask_count": int,         # 问答次数
                "avg_ask_latency_ms": float,
                "tool_call_count": int,   # 工具调用次数
                "llm_token_total": int,   # LLM token 总消耗
                "ingest_count": int,      # 摄入次数
                "avg_ingest_latency_ms": float,
                "by_hour": [{hour, ask_count, token_total}, ...]  # 按小时分布
            }
        """
        assert self._conn is not None
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()

        # 问答次数（只数 count 行）+ 平均延迟（只取 latency_ms 行）
        ask_row = self._exec(
            """SELECT
                      SUM(CASE WHEN metric_name='count' THEN 1 ELSE 0 END) as cnt,
                      AVG(CASE WHEN metric_name='latency_ms' THEN value END) as avg_lat
               FROM metrics WHERE metric_type='ask' AND created_at >= ?""",
            (cutoff,),
        ).fetchone()

        # 工具调用次数
        tool_row = self._exec(
            "SELECT COUNT(*) as cnt FROM metrics WHERE metric_type='tool_call' AND created_at >= ?",
            (cutoff,),
        ).fetchone()

        # LLM token 总消耗
        token_row = self._exec(
            """SELECT COALESCE(SUM(value), 0) as total
               FROM metrics WHERE metric_type='llm_call' AND metric_name='token_count' AND created_at >= ?""",
            (cutoff,),
        ).fetchone()

        # 摄入次数（只数 count 行）+ 平均延迟
        ingest_row = self._exec(
            """SELECT
                      SUM(CASE WHEN metric_name='count' THEN 1 ELSE 0 END) as cnt,
                      AVG(CASE WHEN metric_name='latency_ms' THEN value END) as avg_lat
               FROM metrics WHERE metric_type='ingest' AND created_at >= ?""",
            (cutoff,),
        ).fetchone()

        # 按小时分布（最近 24 小时的问答数和 token）
        hourly_rows = self._exec(
            """SELECT to_char(created_at::timestamp, 'HH24') as hour,
                      SUM(CASE WHEN metric_type='ask' AND metric_name='count' THEN 1 ELSE 0 END) as ask_cnt,
                      SUM(CASE WHEN metric_type='llm_call' AND metric_name='token_count' THEN value ELSE 0 END) as token_total
               FROM metrics WHERE created_at >= ?
               GROUP BY hour ORDER BY hour""",
            (cutoff,),
        ).fetchall()

        return {
            "ask_count": (ask_row["cnt"] or 0) if ask_row else 0,
            "avg_ask_latency_ms": round(ask_row["avg_lat"], 1) if ask_row and ask_row["avg_lat"] else 0,
            "tool_call_count": tool_row["cnt"] if tool_row else 0,
            "llm_token_total": int(token_row["total"]) if token_row else 0,
            "ingest_count": (ingest_row["cnt"] or 0) if ingest_row else 0,
            "avg_ingest_latency_ms": round(ingest_row["avg_lat"], 1) if ingest_row and ingest_row["avg_lat"] else 0,
            "by_hour": [
                {"hour": r["hour"], "ask_count": r["ask_cnt"] or 0, "token_total": int(r["token_total"] or 0)}
                for r in hourly_rows
            ],
        }

    @_synchronized
    def get_recent_traces(self, limit: int = 20) -> list[dict]:
        """获取最近的问答调用链（看板用）。

        按 trace_id 聚合，返回每条 trace 的汇总信息。
        """
        assert self._conn is not None
        rows = self._exec(
            """SELECT trace_id,
                      MIN(created_at) as started_at,
                      MAX(created_at) as ended_at,
                      COUNT(*) as event_count,
                      SUM(CASE WHEN metric_type='tool_call' THEN 1 ELSE 0 END) as tool_calls,
                      SUM(CASE WHEN metric_type='llm_call' AND metric_name='token_count' THEN value ELSE 0 END) as tokens,
                      AVG(CASE WHEN metric_type='ask' AND metric_name='latency_ms' THEN value END) as ask_latency
               FROM metrics WHERE trace_id IS NOT NULL
               GROUP BY trace_id
               ORDER BY started_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [
            {
                "trace_id": r["trace_id"],
                "started_at": r["started_at"],
                "duration_ms": round(r["ask_latency"], 1) if r["ask_latency"] else 0,
                "tool_calls": r["tool_calls"] or 0,
                "tokens": int(r["tokens"] or 0),
                "event_count": r["event_count"],
            }
            for r in rows
        ]

    @_synchronized
    def get_trace_detail(self, trace_id: str) -> list[dict]:
        """获取某条 trace 的全部指标事件（调用链展开）。"""
        assert self._conn is not None
        import json

        rows = self._exec(
            """SELECT id, metric_type, metric_name, value, metadata, created_at
               FROM metrics WHERE trace_id = ?
               ORDER BY id""",
            (trace_id,),
        ).fetchall()
        result = []
        for r in rows:
            try:
                meta = self._parse_json(r["metadata"]) if r["metadata"] else {}
            except json.JSONDecodeError:
                meta = {}
            result.append({
                "id": r["id"],
                "metric_type": r["metric_type"],
                "metric_name": r["metric_name"],
                "value": r["value"],
                "metadata": meta,
                "created_at": r["created_at"],
            })
        return result

    # ---- Trace Events（完整调用链日志，Phase 5A） ----

    @_synchronized
    def add_trace_event(
        self,
        trace_id: str,
        event_type: str,
        name: str | None = None,
        input_data: str | None = None,
        output: str | None = None,
        token_usage: dict | None = None,
        latency_ms: float | None = None,
        run_id: str | None = None,
    ) -> int:
        """记录一条调用链事件（LLM/工具的完整入参出参）。返回事件 ID。

        Args:
            event_type: 'llm_start' | 'llm_end' | 'tool_start' | 'tool_end'
            name: 模型名 / 工具名
            input_data: 请求 prompt / 工具入参（JSON 字符串）
            output: 响应文本 / 工具出参
            token_usage: LLM token 用量 {prompt, completion, total}
            latency_ms: 本步耗时
            run_id: LangChain run_id（关联 start/end）
        """
        assert self._conn is not None
        import json

        # seq 在同一 trace 内递增
        seq_row = self._exec(
            "SELECT COALESCE(MAX(seq), -1) + 1 as next_seq FROM trace_events WHERE trace_id = ?",
            (trace_id,),
        ).fetchone()
        seq = seq_row["next_seq"] if seq_row else 0

        token_json = json.dumps(token_usage, ensure_ascii=False) if token_usage else None
        now_iso = datetime.now().isoformat()
        cur = self._exec(
            """INSERT INTO trace_events
               (trace_id, seq, event_type, name, input, output, token_usage, latency_ms, run_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id""",
            (trace_id, seq, event_type, name, input_data, output, token_json, latency_ms,
             run_id, now_iso),
        )
        # 同步累加用量计数器（仅 llm_end 有 token_usage 时）
        if event_type == "llm_end" and token_usage and token_usage.get("total", 0) > 0:
            self._increment_usage_counters(token_usage, now_iso)
        self._conn.commit()
        return cur.fetchone()["id"]

    def _increment_usage_counters(self, token_usage: dict, now_iso: str) -> None:
        """累加用量到 today/month/total 三个周期计数器。

        计数器独立于 trace_events（不可变审计日志），重置只清零计数器不删历史。
        跨天/跨月自动轮转：period_key 变了则老行保留、新行从 0 开始。
        """
        from datetime import datetime

        now = datetime.fromisoformat(now_iso)
        today_key = now.strftime("%Y-%m-%d")
        month_key = now.strftime("%Y-%m")
        tokens = int(token_usage.get("total", 0))
        cost = float(token_usage.get("cost", 0.0))

        for period_type, period_key in [("today", today_key), ("month", month_key), ("total", "all")]:
            # UPSERT：存在则累加，不存在则新建（period_key 不匹配时 INSERT 新行）
            self._exec(
                """INSERT INTO usage_counters (period_type, period_key, tokens, cost, calls, updated_at)
                   VALUES (?, ?, ?, ?, 1, ?)
                   ON CONFLICT(period_type, period_key) DO UPDATE SET
                     tokens = usage_counters.tokens + EXCLUDED.tokens,
                     cost = usage_counters.cost + EXCLUDED.cost,
                     calls = usage_counters.calls + 1,
                     updated_at = EXCLUDED.updated_at""",
                (period_type, period_key, tokens, cost, now_iso),
            )

    @_synchronized
    def get_trace_events(self, trace_id: str) -> list[dict]:
        """获取某条 trace 的完整调用链事件（按序号排序，start/end 已合并）。

        返回的事件类型为 'llm' | 'tool'（合并了 start/end），
        每条同时携带 input（来自 start）和 output（来自 end）。
        配对策略：同类型按出现顺序 FIFO（LangGraph 的 run_id 在并行场景下不可靠）。
        """
        assert self._conn is not None
        import json

        rows = self._exec(
            """SELECT id, seq, event_type, name, input, output, token_usage, latency_ms, run_id, created_at
               FROM trace_events WHERE trace_id = ? ORDER BY seq""",
            (trace_id,),
        ).fetchall()

        # 解析原始事件
        def parse_row(r):
            try:
                tu = self._parse_json(r["token_usage"]) if r["token_usage"] else None
            except json.JSONDecodeError:
                tu = None
            return {
                "id": r["id"],
                "seq": r["seq"],
                "event_type": r["event_type"],
                "name": r["name"] or "",
                "input": r["input"] or "",
                "output": r["output"] or "",
                "token_usage": tu,
                "latency_ms": r["latency_ms"],
                "run_id": r["run_id"] or "",
                "created_at": r["created_at"],
            }

        raw_events = [parse_row(r) for r in rows]

        # start/end 配对合并（按类型 FIFO）
        pending: dict[str, list[dict]] = {"llm": [], "tool": []}  # 等待配对的 start 事件
        merged: list[dict] = []
        merged_seq = 0

        for e in raw_events:
            etype = e["event_type"]
            kind = "llm" if etype.startswith("llm") else "tool"

            if etype.endswith("_start"):
                pending[kind].append(e)
            elif etype.endswith("_end"):
                if pending[kind]:
                    start = pending[kind].pop(0)  # FIFO 取最早的 start
                    merged.append({
                        "id": start["id"],
                        "seq": merged_seq,
                        "event_type": kind,
                        "name": start["name"] or e["name"],
                        "input": start["input"],
                        "output": e["output"],
                        "token_usage": e["token_usage"],
                        "latency_ms": e["latency_ms"],
                        "run_id": start["run_id"] or e["run_id"],
                        "created_at": start["created_at"],
                    })
                    merged_seq += 1
                else:
                    # 只有 end 没有 start（异常情况），单独保留
                    merged.append({
                        **e,
                        "seq": merged_seq,
                        "event_type": kind,
                    })
                    merged_seq += 1

        # 还有未配对的 start（流中断等），也保留
        for kind, starts in pending.items():
            for start in starts:
                merged.append({
                    **start,
                    "seq": merged_seq,
                    "event_type": kind,
                })
                merged_seq += 1

        return merged

    # ---- 成本统计（Phase 5B FR48/FR49） ----

    @_synchronized
    def get_cost_summary(self) -> dict:
        """获取成本汇总（今日/本月/总累计 + 配额用量）。

        从 usage_counters 表读取（独立计数器），不再 SUM trace_events。
        重置只清零计数器，不删除历史调用记录。
        """
        assert self._conn is not None
        from datetime import datetime

        now = datetime.now()
        today_key = now.strftime("%Y-%m-%d")
        month_key = now.strftime("%Y-%m")

        def _read(period_type: str, period_key: str) -> tuple[float, int]:
            """返回 (成本, token) — 从 usage_counters 读取指定周期。"""
            row = self._exec(
                "SELECT COALESCE(tokens, 0) as tokens, COALESCE(cost, 0) as cost "
                "FROM usage_counters WHERE period_type=? AND period_key=?",
                (period_type, period_key),
            ).fetchone()
            if row:
                return round(float(row["cost"]), 6), int(row["tokens"])
            return 0.0, 0

        today_cost, today_tokens = _read("today", today_key)
        month_cost, month_tokens = _read("month", month_key)
        total_cost, total_tokens = _read("total", "all")

        return {
            "today": {"cost": today_cost, "tokens": today_tokens},
            "month": {"cost": month_cost, "tokens": month_tokens},
            "total": {"cost": total_cost, "tokens": total_tokens},
        }

    @_synchronized
    def reset_usage_counters(self, period: str = "today") -> None:
        """重置用量计数器（不删除历史调用记录）。

        Args:
            period: 'today' | 'month' — 重置今日或本月计数器。
                    'total' 不允许重置（累计值不可变）。
        """
        assert self._conn is not None
        assert period in ("today", "month"), f"不支持重置周期: {period}"
        from datetime import datetime

        now = datetime.now()
        period_key = now.strftime("%Y-%m-%d") if period == "today" else now.strftime("%Y-%m")
        self._exec(
            "DELETE FROM usage_counters WHERE period_type=? AND period_key=?",
            (period, period_key),
        )
        self._conn.commit()
        logger.info(f"用量计数器已重置: {period} (period_key={period_key})")

    @_synchronized
    def get_cost_by_model(self, hours: int = 24) -> list[dict]:
        """按模型聚合成本（最近 N 小时）。"""
        assert self._conn is not None
        from datetime import datetime, timedelta

        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
        rows = self._exec(
            """SELECT
                    COALESCE(name, 'unknown') as model,
                    SUM(json_extract(token_usage, '$.prompt')) as prompt_t,
                    SUM(json_extract(token_usage, '$.completion')) as completion_t,
                    SUM(json_extract(token_usage, '$.total')) as total_t,
                    SUM(json_extract(token_usage, '$.cost')) as cost,
                    COUNT(*) as calls
               FROM trace_events
               WHERE event_type='llm_end' AND token_usage IS NOT NULL
                 AND created_at >= ?
               GROUP BY model ORDER BY cost DESC""",
            (cutoff,),
        ).fetchall()
        return [
            {
                "model": r["model"],
                "prompt_tokens": int(r["prompt_t"] or 0),
                "completion_tokens": int(r["completion_t"] or 0),
                "total_tokens": int(r["total_t"] or 0),
                "cost": round(r["cost"] or 0, 6),
                "calls": r["calls"],
            }
            for r in rows
        ]

    @_synchronized
    def get_cost_by_day(self, days: int = 30) -> list[dict]:
        """按日聚合成本（最近 N 天）。"""
        assert self._conn is not None
        from datetime import datetime, timedelta

        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        rows = self._exec(
            """SELECT
                    substr(created_at, 1, 10) as day,
                    SUM(json_extract(token_usage, '$.total')) as total_t,
                    SUM(json_extract(token_usage, '$.cost')) as cost,
                    COUNT(*) as calls
               FROM trace_events
               WHERE event_type='llm_end' AND token_usage IS NOT NULL
                 AND created_at >= ?
               GROUP BY day ORDER BY day""",
            (cutoff,),
        ).fetchall()
        return [
            {
                "day": r["day"],
                "total_tokens": int(r["total_t"] or 0),
                "cost": round(r["cost"] or 0, 6),
                "calls": r["calls"],
            }
            for r in rows
        ]

    # ---- 评估分数（Phase 5D FR55） ----

    @_synchronized
    def add_eval_score(
        self,
        trace_id: str | None,
        question: str,
        answer: str,
        score: int,
        dimensions: dict | None = None,
        comment: str | None = None,
        run_id: int | None = None,
    ) -> int:
        """记录一条 LLM-as-Judge 打分。返回 ID。"""
        assert self._conn is not None
        import json

        dim_json = json.dumps(dimensions, ensure_ascii=False) if dimensions else None
        cur = self._exec(
            """INSERT INTO eval_scores (trace_id, question, answer, score, dimensions, comment, run_id, judged_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?) RETURNING id""",
            (trace_id, question[:500], answer[:1000], score, dim_json, comment,
             run_id, datetime.now().isoformat()),
        )
        self._conn.commit()
        return cur.fetchone()["id"]

    @_synchronized
    def get_eval_scores(self, limit: int = 50) -> list[dict]:
        """获取最近的评估打分（按时间倒序）。"""
        assert self._conn is not None
        import json

        rows = self._exec(
            """SELECT id, trace_id, question, answer, score, dimensions, comment, judged_at
               FROM eval_scores ORDER BY judged_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        result = []
        for r in rows:
            try:
                dims = self._parse_json(r["dimensions"]) if r["dimensions"] else None
            except json.JSONDecodeError:
                dims = None
            result.append({
                "id": r["id"],
                "trace_id": r["trace_id"] or "",
                "question": r["question"] or "",
                "answer": r["answer"] or "",
                "score": r["score"],
                "dimensions": dims,
                "comment": r["comment"] or "",
                "judged_at": r["judged_at"],
            })
        return result

    @_synchronized
    def get_eval_score_summary(self) -> dict:
        """评估打分汇总（平均分/总数/分布）。"""
        assert self._conn is not None
        row = self._exec(
            """SELECT
                    COUNT(*) as cnt,
                    AVG(score) as avg_score,
                    SUM(CASE WHEN score >= 4 THEN 1 ELSE 0 END) as good,
                    SUM(CASE WHEN score = 3 THEN 1 ELSE 0 END) as mid,
                    SUM(CASE WHEN score <= 2 THEN 1 ELSE 0 END) as bad
               FROM eval_scores"""
        ).fetchone()
        return {
            "total": row["cnt"] if row else 0,
            "avg_score": round(row["avg_score"], 2) if row and row["avg_score"] else 0,
            "distribution": {
                "good": row["good"] if row else 0,   # 4-5 分
                "mid": row["mid"] if row else 0,      # 3 分
                "bad": row["bad"] if row else 0,       # 1-2 分
            },
        }

    # ---- 评估批次历史（Phase 5D） ----

    @_synchronized
    def add_eval_run(
        self,
        run_type: str,
        total: int,
        passed: int | None = None,
        pass_rate: float | None = None,
        avg_score: float | None = None,
        duration_ms: float | None = None,
        details: dict | None = None,
    ) -> int:
        """记录一次评估批次。返回 run_id。"""
        assert self._conn is not None
        import json

        details_json = json.dumps(details, ensure_ascii=False) if details else None
        cur = self._exec(
            """INSERT INTO eval_runs
               (run_type, total, passed, pass_rate, avg_score, duration_ms, details, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?) RETURNING id""",
            (run_type, total, passed, pass_rate, avg_score, duration_ms, details_json,
             datetime.now().isoformat()),
        )
        self._conn.commit()
        return cur.fetchone()["id"]

    @_synchronized
    def get_eval_runs(self, limit: int = 20, run_type: str | None = None) -> list[dict]:
        """获取评估批次历史（按时间倒序）。"""
        assert self._conn is not None
        import json

        sql = "SELECT * FROM eval_runs"
        params: list = []
        if run_type:
            sql += " WHERE run_type=?"
            params.append(run_type)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = self._exec(sql, params).fetchall()
        result = []
        for r in rows:
            try:
                det = self._parse_json(r["details"]) if r["details"] else None
            except json.JSONDecodeError:
                det = None
            result.append({
                "id": r["id"],
                "run_type": r["run_type"],
                "total": r["total"],
                "passed": r["passed"],
                "pass_rate": r["pass_rate"],
                "avg_score": r["avg_score"],
                "duration_ms": r["duration_ms"],
                "details": det,
                "created_at": r["created_at"],
            })
        return result

    @_synchronized
    def update_eval_run(self, run_id: int, **fields) -> bool:
        """更新评估批次记录。"""
        assert self._conn is not None
        import json

        allowed = {"total", "passed", "pass_rate", "avg_score", "duration_ms", "details"}
        updates = {}
        for k, v in fields.items():
            if k not in allowed:
                continue
            if k == "details" and isinstance(v, dict):
                updates[k] = json.dumps(v, ensure_ascii=False)
            else:
                updates[k] = v
        if not updates:
            return False
        set_clause = ", ".join(f"{k}=?" for k in updates)
        params = list(updates.values()) + [run_id]
        cur = self._exec(
            f"UPDATE eval_runs SET {set_clause} WHERE id=?", params
        )
        self._conn.commit()
        return cur.rowcount > 0

    # ---- Golden Cases（测试集，Phase 5D FR53） ----

    @_synchronized
    def add_golden_case(
        self,
        case_id: str,
        question: str,
        expected_keywords: list[str] | None = None,
        expected_sources: list[str] | None = None,
        min_score: float = 0.7,
        enabled: bool = True,
    ) -> str:
        """新增/覆盖一条 golden case。返回 case_id。"""
        assert self._conn is not None
        import json

        now = datetime.now().isoformat()
        kw_json = json.dumps(expected_keywords or [], ensure_ascii=False)
        src_json = json.dumps(expected_sources or [], ensure_ascii=False)
        self._exec(
            """INSERT INTO golden_cases (id, question, expected_keywords, expected_sources, min_score, enabled, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 question=excluded.question,
                 expected_keywords=excluded.expected_keywords,
                 expected_sources=excluded.expected_sources,
                 min_score=excluded.min_score,
                 enabled=excluded.enabled,
                 updated_at=excluded.updated_at""",
            (case_id, question, kw_json, src_json, min_score, int(enabled), now, now),
        )
        self._conn.commit()
        return case_id

    @_synchronized
    def get_golden_cases(self, enabled_only: bool = False) -> list[dict]:
        """获取全部 golden cases。"""
        assert self._conn is not None
        import json

        sql = "SELECT * FROM golden_cases"
        if enabled_only:
            sql += " WHERE enabled=1"
        sql += " ORDER BY id"
        rows = self._exec(sql).fetchall()
        result = []
        for r in rows:
            try:
                kw = self._parse_json(r["expected_keywords"]) if r["expected_keywords"] else []
            except json.JSONDecodeError:
                kw = []
            try:
                src = self._parse_json(r["expected_sources"]) if r["expected_sources"] else []
            except json.JSONDecodeError:
                src = []
            result.append({
                "id": r["id"],
                "question": r["question"],
                "expected_keywords": kw,
                "expected_sources": src,
                "min_score": r["min_score"],
                "enabled": bool(r["enabled"]),
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            })
        return result

    @_synchronized
    def update_golden_case(self, case_id: str, **fields) -> bool:
        """更新 golden case 的字段。返回是否成功。"""
        assert self._conn is not None
        import json

        allowed = {"question", "expected_keywords", "expected_sources", "min_score", "enabled"}
        updates = {}
        for k, v in fields.items():
            if k not in allowed:
                continue
            if k in ("expected_keywords", "expected_sources"):
                updates[k] = json.dumps(v or [], ensure_ascii=False)
            elif k == "enabled":
                updates[k] = int(v)
            else:
                updates[k] = v
        if not updates:
            return False
        updates["updated_at"] = datetime.now().isoformat()
        set_clause = ", ".join(f"{k}=?" for k in updates)
        params = list(updates.values()) + [case_id]
        cur = self._exec(
            f"UPDATE golden_cases SET {set_clause} WHERE id=?", params
        )
        self._conn.commit()
        return cur.rowcount > 0

    @_synchronized
    def delete_golden_case(self, case_id: str) -> bool:
        """删除 golden case。"""
        assert self._conn is not None
        cur = self._exec("DELETE FROM golden_cases WHERE id=?", (case_id,))
        self._conn.commit()
        return cur.rowcount > 0

    # ---- Bad Cases（Phase 5D FR54） ----

    @_synchronized
    def add_bad_case(
        self,
        trace_id: str | None,
        question: str,
        answer: str,
        reason: str,
        extra: dict | None = None,
    ) -> int:
        """记录一条 bad case。返回 ID。"""
        assert self._conn is not None
        import json

        extra_json = json.dumps(extra, ensure_ascii=False) if extra else None
        cur = self._exec(
            """INSERT INTO bad_cases (trace_id, question, answer, reason, extra, collected_at)
               VALUES (?, ?, ?, ?, ?, ?) RETURNING id""",
            (trace_id, question[:500], answer[:1000] if answer else "",
             reason, extra_json, datetime.now().isoformat()),
        )
        self._conn.commit()
        return cur.fetchone()["id"]

    @_synchronized
    def get_bad_cases(self, limit: int = 100) -> list[dict]:
        """获取 bad cases（按时间倒序）。"""
        assert self._conn is not None
        import json

        rows = self._exec(
            "SELECT * FROM bad_cases ORDER BY collected_at DESC LIMIT ?", (limit,)
        ).fetchall()
        result = []
        for r in rows:
            try:
                extra = self._parse_json(r["extra"]) if r["extra"] else None
            except json.JSONDecodeError:
                extra = None
            result.append({
                "id": r["id"],
                "trace_id": r["trace_id"] or "",
                "question": r["question"] or "",
                "answer": r["answer"] or "",
                "reason": r["reason"],
                "extra": extra,
                "collected_at": r["collected_at"],
            })
        return result

    @_synchronized
    def delete_bad_case(self, case_id: int) -> bool:
        """删除 bad case。"""
        assert self._conn is not None
        cur = self._exec("DELETE FROM bad_cases WHERE id=?", (case_id,))
        self._conn.commit()
        return cur.rowcount > 0

    # ---- Helpers ----

    @staticmethod
    def _row_to_note(row) -> NoteMetadata:
        return NoteMetadata(
            id=row["id"], title=row["title"],
            source_type=SourceType(row["source_type"]) if row["source_type"] else SourceType.MARKDOWN,
            source_path=row["source_path"], file_hash=row["file_hash"],
            content_preview=row["content_preview"] or "",
            content_length=row["content_length"] or 0,
            chunk_count=row["chunk_count"] or 0,
            status=NoteStatus(row["status"]) if row["status"] else NoteStatus.ACTIVE,
            created_at=row["created_at"] or "",
            updated_at=row["updated_at"] or "",
            ingested_at=row["ingested_at"],
        )

    @staticmethod
    def _row_to_connection(row) -> Connection:
        return Connection(
            id=row["id"], source_note_id=row["source_note_id"],
            target_note_id=row["target_note_id"],
            relation_type=RelationType(row["relation_type"]) if row["relation_type"] else RelationType.RELATED,
            strength=row["strength"] or 0.5, description=row["description"],
            is_ai_generated=bool(row["is_ai_generated"]),
            created_at=row["created_at"] or "",
        )

    # ---- Prompts（提示词外部化，Phase 5E FR56） ----

    @_synchronized
    def get_prompt(self, prompt_key: str) -> dict | None:
        """获取单条提示词（含全部字段）。不存在返回 None。"""
        assert self._conn is not None
        row = self._exec(
            "SELECT prompt_key, name, description, content, is_template, enabled, version, updated_at "
            "FROM prompts WHERE prompt_key=?",
            (prompt_key,),
        ).fetchone()
        if not row:
            return None
        return {
            "prompt_key": row["prompt_key"],
            "name": row["name"],
            "description": row["description"],
            "content": row["content"],
            "is_template": bool(row["is_template"]),
            "enabled": bool(row["enabled"]),
            "version": row["version"],
            "updated_at": row["updated_at"],
        }

    @_synchronized
    def list_prompts(self) -> list[dict]:
        """列出全部提示词（不含 content 正文，列表展示用）。"""
        assert self._conn is not None
        rows = self._exec(
            "SELECT prompt_key, name, description, is_template, enabled, version, updated_at "
            "FROM prompts ORDER BY prompt_key"
        ).fetchall()
        return [
            {
                "prompt_key": r["prompt_key"],
                "name": r["name"],
                "description": r["description"],
                "is_template": bool(r["is_template"]),
                "enabled": bool(r["enabled"]),
                "version": r["version"],
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]

    @_synchronized
    def update_prompt(self, prompt_key: str, content: str, enabled: bool | None = None) -> bool:
        """更新提示词内容（version 自增），并归档旧版本到 prompt_versions。返回是否成功。"""
        assert self._conn is not None
        from datetime import datetime

        # 先读取旧内容，归档到历史表
        old = self.get_prompt(prompt_key)
        if old:
            self._exec(
                "INSERT INTO prompt_versions (prompt_key, version, content, saved_at) "
                "VALUES (?, ?, ?, ?)",
                (prompt_key, old["version"], old["content"], datetime.now().isoformat()),
            )

        # 动态拼接 SET 子句：content/version/updated_at 必更新，enabled 可选
        sets = ["content = ?", "version = version + 1", "updated_at = ?"]
        params: list = [content, datetime.now().isoformat()]
        if enabled is not None:
            sets.append("enabled = ?")
            params.append(1 if enabled else 0)
        params.append(prompt_key)
        cur = self._exec(
            f"UPDATE prompts SET {', '.join(sets)} WHERE prompt_key=?",
            tuple(params),
        )
        self._conn.commit()
        return cur.rowcount > 0

    @_synchronized
    def list_prompt_versions(self, prompt_key: str) -> list[dict]:
        """列出某提示词的历史版本（按版本号降序，不含正文）。"""
        assert self._conn is not None
        rows = self._exec(
            "SELECT version, saved_at FROM prompt_versions "
            "WHERE prompt_key=? ORDER BY version DESC",
            (prompt_key,),
        ).fetchall()
        return [
            {"version": r["version"], "saved_at": r["saved_at"]}
            for r in rows
        ]

    @_synchronized
    def get_prompt_version(self, prompt_key: str, version: int) -> dict | None:
        """获取某提示词指定历史版本的正文。不存在返回 None。"""
        assert self._conn is not None
        row = self._exec(
            "SELECT version, content, saved_at FROM prompt_versions "
            "WHERE prompt_key=? AND version=?",
            (prompt_key, version),
        ).fetchone()
        if not row:
            return None
        return {
            "version": row["version"],
            "content": row["content"],
            "saved_at": row["saved_at"],
        }

    @_synchronized
    def restore_prompt_version(self, prompt_key: str, version: int) -> bool:
        """恢复某历史版本（把该版本内容设为最新，version 继续自增）。"""
        assert self._conn is not None
        hist = self.get_prompt_version(prompt_key, version)
        if not hist:
            return False
        return self.update_prompt(prompt_key, hist["content"])
