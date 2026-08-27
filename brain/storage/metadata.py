"""SQLite 元数据存储（同步）。

管理笔记元数据、标签、关联关系、摄入日志的 CRUD 操作。
使用 sqlite3（线程安全），供 DeepAgents 工具在任意线程中直调。
"""

import sqlite3
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

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
    """装饰器——用实例锁串行化数据库操作。

    LangGraph 的工具节点会并行执行多个工具，同一 SQLite 连接
    不能并发访问，必须加锁。
    """

    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper


class MetadataStore:
    """SQLite 元数据管理—notes / tags / note_tags / connections / ingestion_log。

    所有方法为同步调用，通过实例锁保证多线程安全。
    """

    def __init__(self, db_path: Path):
        self._db_path = str(db_path)
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()

    # ---- 生命周期 ----

    @_synchronized
    def initialize(self) -> None:
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._create_tables()
        logger.info(f"MetadataStore 已连接: {self._db_path}")

    @_synchronized
    def close(self) -> None:
        if self._conn:
            self._conn.close()
            logger.info("MetadataStore 已关闭")

    def _create_tables(self) -> None:
        assert self._conn is not None
        self._conn.executescript("""
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
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,              -- 'user' | 'assistant'
                content TEXT NOT NULL,
                timeline TEXT DEFAULT '[]',      -- JSON: 工具调用轨迹 [{kind, name, args, done}]
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS knowledge_fragments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_type TEXT NOT NULL,       -- 'daily' | 'weekly'
                report_date TEXT NOT NULL,       -- 报告日期（daily: 昨日日期; weekly: 周一日期）
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(report_type, report_date)
            );

            CREATE TABLE IF NOT EXISTS rss_feeds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL UNIQUE,
                title TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                last_fetched_at TEXT,
                entry_count INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS rss_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                feed_id INTEGER NOT NULL,
                entry_id TEXT NOT NULL,          -- feed 条目的唯一 ID（去重）
                title TEXT NOT NULL,
                link TEXT DEFAULT '',
                note_id TEXT DEFAULT '',         -- 摄入后生成的笔记 ID
                published_at TEXT DEFAULT '',
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
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trace_id TEXT,
                metric_type TEXT NOT NULL,
                metric_name TEXT NOT NULL,
                value REAL NOT NULL,
                metadata TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_metrics_type_time ON metrics(metric_type, created_at);
            CREATE INDEX IF NOT EXISTS idx_metrics_trace ON metrics(trace_id);
        """)
        self._conn.commit()

        # trace_events 表单独创建（可能跨连接迁移）
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS trace_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trace_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                name TEXT,
                input TEXT,
                output TEXT,
                token_usage TEXT,
                latency_ms REAL,
                run_id TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_trace_events_trace ON trace_events(trace_id, seq);
            CREATE INDEX IF NOT EXISTS idx_trace_events_trace ON trace_events(trace_id, seq);

            -- 评估分数表（Phase 5D FR55）：LLM-as-Judge 打分
            CREATE TABLE IF NOT EXISTS eval_scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_type TEXT NOT NULL,     -- 'offline' | 'judge'
                total INTEGER,
                passed INTEGER,
                pass_rate REAL,
                avg_score REAL,
                duration_ms REAL,
                details TEXT,               -- JSON 摘要
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_eval_runs_created ON eval_runs(created_at);
            """
        )
        self._conn.commit()

        # golden_cases / bad_cases 表（Phase 5D：测试集存数据库支持页面 CRUD）
        self._conn.executescript(
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
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trace_id TEXT,
                question TEXT,
                answer TEXT,
                reason TEXT,
                extra TEXT,
                collected_at TEXT NOT NULL
            );
            """
        )
        self._conn.commit()

        # 数据库迁移：补充旧表缺失的列/表（CREATE TABLE IF NOT EXISTS 不会改已有表）
        self._migrate()

    def _migrate(self) -> None:
        """增量迁移：为旧数据库补充新增的列和表。"""
        assert self._conn is not None

        def has_column(table: str, column: str) -> bool:
            cols = [r[1] for r in self._conn.execute(f"PRAGMA table_info({table})").fetchall()]
            return column in cols

        def has_table(table: str) -> bool:
            r = self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            return r is not None

        # eval_scores 补 run_id 列（Phase 5D 评估批次关联）
        if has_table("eval_scores") and not has_column("eval_scores", "run_id"):
            self._conn.execute("ALTER TABLE eval_scores ADD COLUMN run_id INTEGER")
            logger.info("迁移: eval_scores 表新增 run_id 列")

        # eval_runs 表（旧库可能没有）
        if not has_table("eval_runs"):
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS eval_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_type TEXT NOT NULL,
                    total INTEGER,
                    passed INTEGER,
                    pass_rate REAL,
                    avg_score REAL,
                    duration_ms REAL,
                    details TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_eval_runs_created ON eval_runs(created_at);
                """
            )
            logger.info("迁移: 新建 eval_runs 表")

        self._conn.commit()

    # ---- Notes CRUD ----

    @_synchronized
    def create_note(self, note: NoteMetadata) -> str:
        assert self._conn is not None
        self._conn.execute(
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
        self._conn.commit()
        logger.debug(f"MetadataStore: 已创建笔记 {note.id} — {note.title}")
        return note.id

    @_synchronized
    def get_note(self, note_id: str) -> NoteMetadata | None:
        assert self._conn is not None
        row = self._conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
        if row is None:
            return None
        return self._row_to_note(row)

    @_synchronized
    def list_notes(
        self, status: NoteStatus = NoteStatus.ACTIVE, limit: int = 50, offset: int = 0,
    ) -> list[NoteMetadata]:
        assert self._conn is not None
        rows = self._conn.execute(
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
        self._conn.execute(f"UPDATE notes SET {set_clause} WHERE id = ?", values)
        self._conn.commit()

    @_synchronized
    def delete_note(self, note_id: str, soft: bool = True) -> None:
        assert self._conn is not None
        if soft:
            self._conn.execute("UPDATE notes SET status = ? WHERE id = ?",
                               (NoteStatus.DELETED.value, note_id))
        else:
            self._conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        self._conn.commit()
        logger.info(f"MetadataStore: 已{'软' if soft else '硬'}删除笔记 {note_id}")

    @_synchronized
    def note_exists(self, file_hash: str) -> str | None:
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT id FROM notes WHERE file_hash = ? AND status = 'active'",
            (file_hash,),
        ).fetchone()
        return row["id"] if row else None

    @_synchronized
    def count_notes(self, status: NoteStatus = NoteStatus.ACTIVE) -> int:
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT COUNT(*) as cnt FROM notes WHERE status = ?", (status.value,),
        ).fetchone()
        return row["cnt"] if row else 0

    # ---- Tags ----

    @_synchronized
    def get_or_create_tag(self, name: str, category: TagCategory, is_ai: bool = False) -> int:
        assert self._conn is not None
        row = self._conn.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()
        if row:
            return row["id"]
        cur = self._conn.execute(
            "INSERT INTO tags (name, category, is_ai_generated) VALUES (?, ?, ?)",
            (name, category.value, int(is_ai)),
        )
        self._conn.commit()
        return cur.lastrowid

    @_synchronized
    def add_tag_to_note(self, note_id: str, tag_id: int, confidence: float | None = None) -> None:
        assert self._conn is not None
        self._conn.execute(
            "INSERT OR REPLACE INTO note_tags (note_id, tag_id, confidence) VALUES (?, ?, ?)",
            (note_id, tag_id, confidence),
        )
        self._conn.commit()

    @_synchronized
    def get_note_tags(self, note_id: str) -> list[Tag]:
        assert self._conn is not None
        rows = self._conn.execute(
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

    # ---- Connections ----

    @_synchronized
    def add_connection(self, conn: Connection) -> int:
        assert self._conn is not None
        cur = self._conn.execute(
            """INSERT INTO connections
               (source_note_id, target_note_id, relation_type, strength,
                description, created_at, is_ai_generated)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (conn.source_note_id, conn.target_note_id, conn.relation_type.value,
             conn.strength, conn.description, conn.created_at, int(conn.is_ai_generated)),
        )
        self._conn.commit()
        return cur.lastrowid

    @_synchronized
    def get_connections(self, note_id: str) -> list[Connection]:
        assert self._conn is not None
        rows = self._conn.execute(
            """SELECT * FROM connections
               WHERE source_note_id = ? OR target_note_id = ?
               ORDER BY strength DESC""",
            (note_id, note_id),
        ).fetchall()
        return [self._row_to_connection(r) for r in rows]

    # ---- Ingestion Log ----

    @_synchronized
    def log_event(self, note_id: str, event: str, status: str,
                  message: str = "", duration_ms: int | None = None) -> None:
        assert self._conn is not None
        self._conn.execute(
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
        self._conn.execute(
            "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (session_id, title, now, now),
        )
        self._conn.commit()
        return session_id

    @_synchronized
    def list_sessions(self, limit: int = 50) -> list[dict]:
        """列出会话（按最近更新排序）。"""
        assert self._conn is not None
        rows = self._conn.execute(
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
        row = self._conn.execute(
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
        self._conn.execute(
            "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?",
            (title, datetime.now().isoformat(), session_id),
        )
        self._conn.commit()

    @_synchronized
    def touch_session(self, session_id: str) -> None:
        """刷新会话的 updated_at（有新消息时调用）。"""
        assert self._conn is not None
        self._conn.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = ?",
            (datetime.now().isoformat(), session_id),
        )
        self._conn.commit()

    @_synchronized
    def delete_session(self, session_id: str) -> None:
        """删除会话（消息级联删除）。"""
        assert self._conn is not None
        self._conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        self._conn.commit()

    # ---- Messages（会话消息） ----

    @_synchronized
    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        timeline: list | None = None,
    ) -> int:
        """保存一条消息。返回消息 ID。"""
        assert self._conn is not None
        import json

        timeline_json = json.dumps(timeline or [], ensure_ascii=False)
        cur = self._conn.execute(
            """INSERT INTO messages (session_id, role, content, timeline, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (session_id, role, content, timeline_json, datetime.now().isoformat()),
        )
        self._conn.commit()
        return cur.lastrowid

    @_synchronized
    def get_messages(self, session_id: str) -> list[dict]:
        """获取会话的全部消息（按时间正序）。"""
        assert self._conn is not None
        import json

        rows = self._conn.execute(
            "SELECT id, role, content, timeline, created_at FROM messages WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
        result = []
        for r in rows:
            try:
                timeline = json.loads(r["timeline"] or "[]")
            except json.JSONDecodeError:
                timeline = []
            result.append(
                {
                    "id": r["id"],
                    "role": r["role"],
                    "content": r["content"],
                    "timeline": timeline,
                    "created_at": r["created_at"],
                }
            )
        return result

    @_synchronized
    def count_messages(self, session_id: str) -> int:
        """会话消息数。"""
        assert self._conn is not None
        row = self._conn.execute(
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
        cur = self._conn.execute(
            """INSERT INTO knowledge_fragments (session_id, title, content, status, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (session_id, title, content, status, datetime.now().isoformat()),
        )
        self._conn.commit()
        logger.info(f"MetadataStore: 知识片段已保存 — {title}")
        return cur.lastrowid

    @_synchronized
    def list_knowledge_fragments(self, limit: int = 50) -> list[dict]:
        """列出知识片段（按时间倒序）。"""
        assert self._conn is not None
        rows = self._conn.execute(
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
        row = self._conn.execute(
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
        cur = self._conn.execute(
            "DELETE FROM knowledge_fragments WHERE id = ?", (fragment_id,)
        )
        self._conn.commit()
        return cur.rowcount > 0

    @_synchronized
    def search_knowledge_fragments(self, keyword: str, limit: int = 10) -> list[dict]:
        """按关键词模糊搜索知识片段（标题和内容）。"""
        assert self._conn is not None
        pattern = f"%{keyword}%"
        rows = self._conn.execute(
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
        cur = self._conn.execute(
            """INSERT INTO digest_reports (report_type, report_date, content, created_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(report_type, report_date) DO UPDATE SET
                 content = excluded.content,
                 created_at = excluded.created_at""",
            (report_type, report_date, content, datetime.now().isoformat()),
        )
        self._conn.commit()
        return cur.lastrowid

    @_synchronized
    def get_digest_report(self, report_type: str, report_date: str) -> dict | None:
        """按类型和日期获取摘要报告。"""
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT id, report_type, report_date, content, created_at FROM digest_reports WHERE report_type = ? AND report_date = ?",
            (report_type, report_date),
        ).fetchone()
        return dict(row) if row else None

    @_synchronized
    def list_digest_reports(self, limit: int = 10) -> list[dict]:
        """列出最近摘要报告。"""
        assert self._conn is not None
        rows = self._conn.execute(
            "SELECT id, report_type, report_date, content, created_at FROM digest_reports ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ---- Reviews（SM-2 间隔重复） ----

    @_synchronized
    def get_review(self, note_id: str) -> dict | None:
        """获取笔记的复习状态。"""
        assert self._conn is not None
        row = self._conn.execute(
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
        self._conn.execute(
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
        rows = self._conn.execute(
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
        rows = self._conn.execute(
            """SELECT n.id, n.title, n.ingested_at, n.content_preview
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
        rows = self._conn.execute(
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
        rows = self._conn.execute(
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
        rows = self._conn.execute(
            """SELECT t.name, COUNT(*) as cnt
               FROM note_tags nt
               JOIN tags t ON t.id = nt.tag_id
               GROUP BY t.name"""
        ).fetchall()
        return {r["name"]: r["cnt"] for r in rows}

    @_synchronized
    def get_all_connections_flat(self) -> list[dict]:
        """一次 SQL 取全部关联（含两端笔记标题）。"""
        assert self._conn is not None
        rows = self._conn.execute(
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
        rows = self._conn.execute(
            """SELECT note_id, COUNT(*) as degree FROM (
                 SELECT source_note_id AS note_id FROM connections
                 UNION ALL
                 SELECT target_note_id FROM connections
               ) GROUP BY note_id"""
        ).fetchall()
        return {r["note_id"]: r["degree"] for r in rows}

    # ---- RSS Feeds ----

    @_synchronized
    def add_rss_feed(self, url: str) -> int:
        """添加 RSS 源。返回 feed_id。"""
        assert self._conn is not None
        cur = self._conn.execute(
            "INSERT INTO rss_feeds (url, created_at) VALUES (?, ?)",
            (url, datetime.now().isoformat()),
        )
        self._conn.commit()
        return cur.lastrowid

    @_synchronized
    def list_rss_feeds(self) -> list[dict]:
        """列出全部 RSS 源。"""
        assert self._conn is not None
        rows = self._conn.execute(
            "SELECT id, url, title, created_at, last_fetched_at, entry_count FROM rss_feeds ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]

    @_synchronized
    def get_rss_feed(self, feed_id: int) -> dict | None:
        """获取单个 RSS 源。"""
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT id, url, title, created_at, last_fetched_at, entry_count FROM rss_feeds WHERE id = ?",
            (feed_id,),
        ).fetchone()
        return dict(row) if row else None

    @_synchronized
    def delete_rss_feed(self, feed_id: int) -> bool:
        """删除 RSS 源（条目级联删除）。"""
        assert self._conn is not None
        cur = self._conn.execute("DELETE FROM rss_feeds WHERE id = ?", (feed_id,))
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
        self._conn.execute(
            "UPDATE rss_feeds SET title = ?, last_fetched_at = ?, entry_count = entry_count + ? WHERE id = ?",
            (title, now, new_entries, feed_id),
        )
        self._conn.commit()

    @_synchronized
    def rss_entry_exists(self, feed_id: int, entry_id: str) -> bool:
        """检查 feed 条目是否已处理过。"""
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT 1 FROM rss_entries WHERE feed_id = ? AND entry_id = ?",
            (feed_id, entry_id),
        ).fetchone()
        return row is not None

    @_synchronized
    def add_rss_entry(
        self,
        feed_id: int,
        entry_id: str,
        title: str,
        link: str,
        published: str,
        note_id: str = "",
    ) -> int:
        """记录一条已处理的 feed 条目。"""
        assert self._conn is not None
        cur = self._conn.execute(
            """INSERT OR IGNORE INTO rss_entries (feed_id, entry_id, title, link, note_id, published_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (feed_id, entry_id, title, link, note_id, published),
        )
        self._conn.commit()
        return cur.lastrowid

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
        cur = self._conn.execute(
            """INSERT INTO metrics (trace_id, metric_type, metric_name, value, metadata, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (trace_id, metric_type, metric_name, value, meta_json, datetime.now().isoformat()),
        )
        self._conn.commit()
        return cur.lastrowid

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
        ask_row = self._conn.execute(
            """SELECT
                      SUM(CASE WHEN metric_name='count' THEN 1 ELSE 0 END) as cnt,
                      AVG(CASE WHEN metric_name='latency_ms' THEN value END) as avg_lat
               FROM metrics WHERE metric_type='ask' AND created_at >= ?""",
            (cutoff,),
        ).fetchone()

        # 工具调用次数
        tool_row = self._conn.execute(
            "SELECT COUNT(*) as cnt FROM metrics WHERE metric_type='tool_call' AND created_at >= ?",
            (cutoff,),
        ).fetchone()

        # LLM token 总消耗
        token_row = self._conn.execute(
            """SELECT COALESCE(SUM(value), 0) as total
               FROM metrics WHERE metric_type='llm_call' AND metric_name='token_count' AND created_at >= ?""",
            (cutoff,),
        ).fetchone()

        # 摄入次数（只数 count 行）+ 平均延迟
        ingest_row = self._conn.execute(
            """SELECT
                      SUM(CASE WHEN metric_name='count' THEN 1 ELSE 0 END) as cnt,
                      AVG(CASE WHEN metric_name='latency_ms' THEN value END) as avg_lat
               FROM metrics WHERE metric_type='ingest' AND created_at >= ?""",
            (cutoff,),
        ).fetchone()

        # 按小时分布（最近 24 小时的问答数和 token）
        hourly_rows = self._conn.execute(
            """SELECT strftime('%H', created_at) as hour,
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
        rows = self._conn.execute(
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

        rows = self._conn.execute(
            """SELECT id, metric_type, metric_name, value, metadata, created_at
               FROM metrics WHERE trace_id = ?
               ORDER BY id""",
            (trace_id,),
        ).fetchall()
        result = []
        for r in rows:
            try:
                meta = json.loads(r["metadata"]) if r["metadata"] else {}
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
        seq_row = self._conn.execute(
            "SELECT COALESCE(MAX(seq), -1) + 1 as next_seq FROM trace_events WHERE trace_id = ?",
            (trace_id,),
        ).fetchone()
        seq = seq_row["next_seq"] if seq_row else 0

        token_json = json.dumps(token_usage, ensure_ascii=False) if token_usage else None
        cur = self._conn.execute(
            """INSERT INTO trace_events
               (trace_id, seq, event_type, name, input, output, token_usage, latency_ms, run_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (trace_id, seq, event_type, name, input_data, output, token_json, latency_ms,
             run_id, datetime.now().isoformat()),
        )
        self._conn.commit()
        return cur.lastrowid

    @_synchronized
    def get_trace_events(self, trace_id: str) -> list[dict]:
        """获取某条 trace 的完整调用链事件（按序号排序，start/end 已合并）。

        返回的事件类型为 'llm' | 'tool'（合并了 start/end），
        每条同时携带 input（来自 start）和 output（来自 end）。
        配对策略：同类型按出现顺序 FIFO（LangGraph 的 run_id 在并行场景下不可靠）。
        """
        assert self._conn is not None
        import json

        rows = self._conn.execute(
            """SELECT id, seq, event_type, name, input, output, token_usage, latency_ms, run_id, created_at
               FROM trace_events WHERE trace_id = ? ORDER BY seq""",
            (trace_id,),
        ).fetchall()

        # 解析原始事件
        def parse_row(r):
            try:
                tu = json.loads(r["token_usage"]) if r["token_usage"] else None
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

        成本数据从 trace_events.token_usage JSON 的 cost 字段聚合。
        """
        assert self._conn is not None
        from datetime import datetime

        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()

        def _sum_cost(since: str) -> tuple[float, int]:
            """返回 (成本, token) — 从 trace_events 的 token_usage.cost 聚合。"""
            row = self._conn.execute(
                """SELECT
                    COALESCE(SUM(json_extract(token_usage, '$.cost')), 0) as cost,
                    COALESCE(SUM(json_extract(token_usage, '$.total')), 0) as tokens
                   FROM trace_events
                   WHERE event_type='llm_end' AND token_usage IS NOT NULL
                     AND created_at >= ?""",
                (since,),
            ).fetchone()
            return round(row["cost"], 6), int(row["tokens"] or 0)

        today_cost, today_tokens = _sum_cost(today_start)
        month_cost, month_tokens = _sum_cost(month_start)
        total_cost, total_tokens = _sum_cost("1970-01-01")

        return {
            "today": {"cost": today_cost, "tokens": today_tokens},
            "month": {"cost": month_cost, "tokens": month_tokens},
            "total": {"cost": total_cost, "tokens": total_tokens},
        }

    @_synchronized
    def get_cost_by_model(self, hours: int = 24) -> list[dict]:
        """按模型聚合成本（最近 N 小时）。"""
        assert self._conn is not None
        from datetime import datetime, timedelta

        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
        rows = self._conn.execute(
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
        rows = self._conn.execute(
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
        cur = self._conn.execute(
            """INSERT INTO eval_scores (trace_id, question, answer, score, dimensions, comment, run_id, judged_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (trace_id, question[:500], answer[:1000], score, dim_json, comment,
             run_id, datetime.now().isoformat()),
        )
        self._conn.commit()
        return cur.lastrowid

    @_synchronized
    def get_eval_scores(self, limit: int = 50) -> list[dict]:
        """获取最近的评估打分（按时间倒序）。"""
        assert self._conn is not None
        import json

        rows = self._conn.execute(
            """SELECT id, trace_id, question, answer, score, dimensions, comment, judged_at
               FROM eval_scores ORDER BY judged_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        result = []
        for r in rows:
            try:
                dims = json.loads(r["dimensions"]) if r["dimensions"] else None
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
        row = self._conn.execute(
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
        cur = self._conn.execute(
            """INSERT INTO eval_runs
               (run_type, total, passed, pass_rate, avg_score, duration_ms, details, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (run_type, total, passed, pass_rate, avg_score, duration_ms, details_json,
             datetime.now().isoformat()),
        )
        self._conn.commit()
        return cur.lastrowid

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
        rows = self._conn.execute(sql, params).fetchall()
        result = []
        for r in rows:
            try:
                det = json.loads(r["details"]) if r["details"] else None
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
        cur = self._conn.execute(
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
        self._conn.execute(
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
        rows = self._conn.execute(sql).fetchall()
        result = []
        for r in rows:
            try:
                kw = json.loads(r["expected_keywords"]) if r["expected_keywords"] else []
            except json.JSONDecodeError:
                kw = []
            try:
                src = json.loads(r["expected_sources"]) if r["expected_sources"] else []
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
        cur = self._conn.execute(
            f"UPDATE golden_cases SET {set_clause} WHERE id=?", params
        )
        self._conn.commit()
        return cur.rowcount > 0

    @_synchronized
    def delete_golden_case(self, case_id: str) -> bool:
        """删除 golden case。"""
        assert self._conn is not None
        cur = self._conn.execute("DELETE FROM golden_cases WHERE id=?", (case_id,))
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
        cur = self._conn.execute(
            """INSERT INTO bad_cases (trace_id, question, answer, reason, extra, collected_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (trace_id, question[:500], answer[:1000] if answer else "",
             reason, extra_json, datetime.now().isoformat()),
        )
        self._conn.commit()
        return cur.lastrowid

    @_synchronized
    def get_bad_cases(self, limit: int = 100) -> list[dict]:
        """获取 bad cases（按时间倒序）。"""
        assert self._conn is not None
        import json

        rows = self._conn.execute(
            "SELECT * FROM bad_cases ORDER BY collected_at DESC LIMIT ?", (limit,)
        ).fetchall()
        result = []
        for r in rows:
            try:
                extra = json.loads(r["extra"]) if r["extra"] else None
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
        cur = self._conn.execute("DELETE FROM bad_cases WHERE id=?", (case_id,))
        self._conn.commit()
        return cur.rowcount > 0

    # ---- Helpers ----

    @staticmethod
    def _row_to_note(row: sqlite3.Row) -> NoteMetadata:
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
    def _row_to_connection(row: sqlite3.Row) -> Connection:
        return Connection(
            id=row["id"], source_note_id=row["source_note_id"],
            target_note_id=row["target_note_id"],
            relation_type=RelationType(row["relation_type"]) if row["relation_type"] else RelationType.RELATED,
            strength=row["strength"] or 0.5, description=row["description"],
            is_ai_generated=bool(row["is_ai_generated"]),
            created_at=row["created_at"] or "",
        )
