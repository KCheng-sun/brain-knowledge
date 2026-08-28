"""pgvector 向量存储封装。

负责笔记分块、对话记忆、知识片段的向量嵌入和语义检索。
统一存入 PostgreSQL（pgvector 扩展），与业务元数据同库，便于备份和事务一致。

三个表（均以 vec_ 前缀标识为向量检索层）：
  - vec_note_chunks: 笔记分块向量
  - vec_conversation_memory: 对话消息向量（第二层记忆）
  - vec_fragment_memory: 知识片段向量（第三层记忆）

表名前缀约定：
  - 业务元数据表：无前缀（主体，如 notes/sessions/messages）
  - 向量检索表：vec_ 前缀（本模块）
  - 检查点表：checkpoint_ 前缀（LangGraph PostgresSaver 自动创建）
"""

import json

from loguru import logger

from brain.models import Chunk, SearchResult


class VectorStore:
    """pgvector 封装——管理笔记/记忆/片段的向量存储和语义检索。"""

    def __init__(self, dsn: str, embedding_fn, dim: int = 1024):
        """
        Args:
            dsn: PostgreSQL 连接串
            embedding_fn: embedding 函数，签名为 (texts: list[str]) -> list[list[float]]
            dim: 向量维度（BGE-large-zh = 1024）
        """
        import psycopg
        from psycopg.rows import dict_row

        self._embedding_fn = embedding_fn
        self._dim = dim
        self._conn = psycopg.connect(dsn, autocommit=True, row_factory=dict_row)

        self._init_schema()
        logger.info(f"VectorStore 已连接 PostgreSQL (dim={dim}, pgvector)")

    def _init_schema(self) -> None:
        """建表 + 向量索引 + 注释（幂等）。"""
        cur = self._conn.cursor()
        # pgvector 扩展（建在 public，所有 schema 可用）
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")

        # ---- 迁移旧表名（无 vec_ 前缀）到新名（必须在 CREATE 新表之前）----
        self._migrate_table_names(cur)

        # ---- 笔记分块 ----
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS vec_note_chunks (
                id TEXT PRIMARY KEY,
                note_id TEXT NOT NULL,
                chunk_index INT,
                content TEXT,
                metadata JSONB,
                embedding vector({self._dim})
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_vec_note_chunks_note_id "
            "ON vec_note_chunks(note_id)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_vec_note_chunks_hnsw "
            "ON vec_note_chunks USING hnsw (embedding vector_cosine_ops)"
        )

        # ---- 对话记忆 ----
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS vec_conversation_memory (
                id TEXT PRIMARY KEY,
                message_id INT,
                session_id TEXT,
                role TEXT,
                chunk_index INT,
                content TEXT,
                embedding vector({self._dim})
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_vec_conv_mem_session "
            "ON vec_conversation_memory(session_id)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_vec_conv_mem_hnsw "
            "ON vec_conversation_memory USING hnsw (embedding vector_cosine_ops)"
        )

        # ---- 知识片段 ----
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS vec_fragment_memory (
                id TEXT PRIMARY KEY,
                fragment_id INT,
                title TEXT,
                content TEXT,
                embedding vector({self._dim})
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_vec_frag_mem_hnsw "
            "ON vec_fragment_memory USING hnsw (embedding vector_cosine_ops)"
        )

        # ---- 表与列注释 ----
        self._apply_comments(cur)

    # ---- 笔记分块：写入 ----

    def _migrate_table_names(self, cur) -> None:
        """迁移旧表名（无 vec_ 前缀）到新名，兼容已初始化的库。"""
        renames = [
            ("note_chunks", "vec_note_chunks"),
            ("conversation_memory", "vec_conversation_memory"),
            ("fragment_memory", "vec_fragment_memory"),
        ]
        for old_name, new_name in renames:
            # 旧表存在且新表不存在时才 RENAME（避免与新库冲突）
            cur.execute(
                "SELECT to_regclass(%s) AS old_exists, to_regclass(%s) AS new_exists",
                (old_name, new_name),
            )
            row = cur.fetchone()
            if row and row["old_exists"] and not row["new_exists"]:
                cur.execute(f'ALTER TABLE "{old_name}" RENAME TO "{new_name}"')
                logger.info(f"VectorStore: 表 {old_name} → {new_name}（迁移旧名）")

    def _apply_comments(self, cur) -> None:
        """为向量表和关键列添加注释（幂等）。"""
        statements = [
            # ---- vec_note_chunks ----
            "COMMENT ON TABLE vec_note_chunks IS '向量检索层-笔记分块：笔记正文经分块、嵌入后的向量存储，语义检索的主体'",
            "COMMENT ON COLUMN vec_note_chunks.id IS '分块唯一 ID（UUID）'",
            "COMMENT ON COLUMN vec_note_chunks.note_id IS '所属笔记 ID（关联 business.notes.id）'",
            "COMMENT ON COLUMN vec_note_chunks.chunk_index IS '分块在笔记内的序号（从 0 起）'",
            "COMMENT ON COLUMN vec_note_chunks.content IS '分块正文'",
            "COMMENT ON COLUMN vec_note_chunks.metadata IS '附加元数据（JSONB：来源、位置等）'",
            "COMMENT ON COLUMN vec_note_chunks.embedding IS '语义向量（pgvector，1024 维 BGE-large-zh）'",
            # ---- vec_conversation_memory ----
            "COMMENT ON TABLE vec_conversation_memory IS '向量检索层-对话记忆：问答对话消息的向量存储，实现跨会话语义记忆（第二层记忆）'",
            "COMMENT ON COLUMN vec_conversation_memory.id IS '记忆块唯一 ID'",
            "COMMENT ON COLUMN vec_conversation_memory.message_id IS '来源消息 ID（关联 business.messages.id）'",
            "COMMENT ON COLUMN vec_conversation_memory.session_id IS '所属会话 ID（关联 business.sessions.id）'",
            "COMMENT ON COLUMN vec_conversation_memory.role IS '消息角色：user / assistant'",
            "COMMENT ON COLUMN vec_conversation_memory.chunk_index IS '长消息分块序号'",
            "COMMENT ON COLUMN vec_conversation_memory.content IS '消息内容'",
            "COMMENT ON COLUMN vec_conversation_memory.embedding IS '语义向量（pgvector，1024 维）'",
            # ---- vec_fragment_memory ----
            "COMMENT ON TABLE vec_fragment_memory IS '向量检索层-知识片段：HIL 沉淀的精炼知识向量存储（第三层记忆）'",
            "COMMENT ON COLUMN vec_fragment_memory.id IS '片段向量唯一 ID'",
            "COMMENT ON COLUMN vec_fragment_memory.fragment_id IS '来源知识片段 ID（关联 business.knowledge_fragments.id）'",
            "COMMENT ON COLUMN vec_fragment_memory.title IS '片段标题'",
            "COMMENT ON COLUMN vec_fragment_memory.content IS '片段正文'",
            "COMMENT ON COLUMN vec_fragment_memory.embedding IS '语义向量（pgvector，1024 维）'",
        ]
        for stmt in statements:
            try:
                cur.execute(stmt)
            except Exception:
                # 注释失败不阻塞建表流程
                pass

    def add(self, chunks: list[Chunk]) -> list[str]:
        """将分块嵌入后存入。"""
        if not chunks:
            return []

        texts = [chunk.content for chunk in chunks]
        ids = [chunk.id for chunk in chunks]
        metadatas = [
            {
                "note_id": chunk.note_id,
                "chunk_index": chunk.index,
                **chunk.metadata,
            }
            for chunk in chunks
        ]
        embeddings = self._embedding_fn(texts)

        cur = self._conn.cursor()
        for cid, text, meta, emb in zip(ids, texts, metadatas, embeddings, strict=True):
            # pgvector 用 %s 占位符，向量传字符串 "[1,2,3]"
            cur.execute(
                """
                INSERT INTO vec_note_chunks (id, note_id, chunk_index, content, metadata, embedding)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    note_id = EXCLUDED.note_id,
                    chunk_index = EXCLUDED.chunk_index,
                    content = EXCLUDED.content,
                    metadata = EXCLUDED.metadata,
                    embedding = EXCLUDED.embedding
                """,
                (cid, meta.get("note_id"), meta.get("chunk_index"),
                 text, json.dumps(meta, ensure_ascii=False), _vec_to_str(emb)),
            )
        logger.info(f"VectorStore: 已存储 {len(chunks)} 个分块")
        return ids

    # ---- 笔记分块：检索 ----

    def get_note_chunks(self, note_id: str) -> list[SearchResult]:
        """按 note_id 精确取回笔记的全部正文分块（按 chunk_index 升序）。"""
        cur = self._conn.cursor()
        cur.execute(
            "SELECT id, content, metadata FROM vec_note_chunks "
            "WHERE note_id = %s ORDER BY chunk_index",
            (note_id,),
        )
        rows = cur.fetchall()
        if not rows:
            return []

        chunks: list[SearchResult] = []
        for row in rows:
            metadata = json.loads(row["metadata"]) if isinstance(row["metadata"], str) else (row["metadata"] or {})
            chunks.append(
                SearchResult(
                    chunk_id=row["id"],
                    note_id=note_id,
                    note_title=metadata.get("title", ""),
                    content=row["content"] or "",
                    score=1.0,  # 精确匹配，无相似度概念
                    metadata=metadata,
                )
            )
        return chunks

    def search(self, query: str, top_k: int = 10) -> list[SearchResult]:
        """语义搜索——返回与查询最相关的分块。"""
        if not query.strip():
            return []

        query_embedding = self._embedding_fn([query[:300]])[0]
        cur = self._conn.cursor()
        # <=> 余弦距离，1 - distance = 相似度
        cur.execute(
            """
            SELECT id, note_id, content, metadata,
                   1 - (embedding <=> %s::vector) AS score
            FROM vec_note_chunks
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (_vec_to_str(query_embedding), _vec_to_str(query_embedding), top_k),
        )
        rows = cur.fetchall()

        search_results: list[SearchResult] = []
        for row in rows:
            metadata = json.loads(row["metadata"]) if isinstance(row["metadata"], str) else (row["metadata"] or {})
            search_results.append(
                SearchResult(
                    chunk_id=row["id"],
                    note_id=row["note_id"] or "",
                    note_title=metadata.get("title", "无标题"),
                    content=row["content"] or "",
                    score=round(float(row["score"]), 4),
                    metadata=metadata,
                )
            )
        return search_results

    # ---- 笔记分块：删除 ----

    def delete_by_note(self, note_id: str) -> None:
        """删除某条笔记的所有分块。"""
        cur = self._conn.cursor()
        cur.execute("DELETE FROM vec_note_chunks WHERE note_id = %s", (note_id,))
        deleted = cur.rowcount
        if deleted:
            logger.info(f"VectorStore: 已删除笔记 {note_id} 的 {deleted} 个分块")

    # ---- 对话记忆（第二层记忆：历史消息向量检索） ----

    def add_memory(self, message_id: int, session_id: str, role: str, content: str) -> None:
        """把一条对话消息写入记忆表。

        超长消息按 300 字符分块嵌入，每块一个独立向量（id 用 msg_{id}_{chunk_idx} 区分）。
        """
        if not content.strip():
            return

        # 分块：避免超过 BGE 的 512 token 限制
        chunks: list[str] = []
        remaining = content
        while len(remaining) > 300:
            chunks.append(remaining[:300])
            remaining = remaining[300:]
        if remaining:
            chunks.append(remaining)

        cur = self._conn.cursor()
        for i, chunk_text in enumerate(chunks):
            embedding = self._embedding_fn([chunk_text])[0]
            cur.execute(
                """
                INSERT INTO vec_conversation_memory (id, message_id, session_id, role, chunk_index, content, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    content = EXCLUDED.content,
                    embedding = EXCLUDED.embedding
                """,
                (f"msg_{message_id}_{i}", message_id, session_id, role, i,
                 chunk_text, _vec_to_str(embedding)),
            )
        logger.debug(f"VectorStore: 记忆已写入 msg_{message_id} ({role}, {len(chunks)} 块)")

    def search_memory(
        self,
        query: str,
        top_k: int = 5,
        current_session: str | None = None,
        session_boost: float = 0.15,
    ) -> list[SearchResult]:
        """检索与查询相关的历史对话消息（跨会话）。

        同会话消息加分（session_boost），保住超过工作窗口的旧消息的对话连续性。
        """
        if not query.strip():
            return []

        query_embedding = self._embedding_fn([query[:300]])[0]
        cur = self._conn.cursor()
        # 检索更多候选，加权重排后截断
        cur.execute(
            """
            SELECT id, session_id, role, content,
                   1 - (embedding <=> %s::vector) AS base_score
            FROM vec_conversation_memory
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (_vec_to_str(query_embedding), _vec_to_str(query_embedding),
             min(top_k * 4, 40)),
        )
        rows = cur.fetchall()

        search_results: list[SearchResult] = []
        for row in rows:
            score = float(row["base_score"])
            # 同会话加权：旧消息在竞争中优先
            is_current = current_session and row["session_id"] == current_session
            if is_current:
                score += session_boost

            search_results.append(
                SearchResult(
                    chunk_id=row["id"],
                    note_id=row["session_id"] or "",
                    note_title=f"{row['role'] or '?'}消息",
                    content=row["content"] or "",
                    score=round(score, 4),
                    metadata={
                        "message_id": None,
                        "session_id": row["session_id"],
                        "role": row["role"],
                        "is_current_session": bool(is_current),
                    },
                )
            )

        # 加权重排后取 top_k
        search_results.sort(key=lambda r: r.score, reverse=True)
        return search_results[:top_k]

    def delete_session_memory(self, session_id: str) -> None:
        """删除某会话的全部记忆向量。"""
        cur = self._conn.cursor()
        cur.execute("DELETE FROM vec_conversation_memory WHERE session_id = %s", (session_id,))
        deleted = cur.rowcount
        if deleted:
            logger.info(f"VectorStore: 已删除会话 {session_id} 的 {deleted} 条记忆")

    # ---- 知识片段（第三层记忆：向量化 + 语义检索） ----

    def add_fragment(self, fragment_id: int, title: str, content: str) -> None:
        """知识片段向量化入库（标题+内容拼接后整体嵌入）。"""
        text = f"{title}。{content}".strip()
        if not text:
            return

        embedding = self._embedding_fn([text[:500]])[0]
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO vec_fragment_memory (id, fragment_id, title, content, embedding)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                title = EXCLUDED.title,
                content = EXCLUDED.content,
                embedding = EXCLUDED.embedding
            """,
            (f"frag_{fragment_id}", fragment_id, title, text[:500],
             _vec_to_str(embedding)),
        )
        logger.debug(f"VectorStore: 片段向量已写入 frag_{fragment_id}")

    def delete_fragment(self, fragment_id: int) -> None:
        """删除片段的向量。"""
        cur = self._conn.cursor()
        cur.execute("DELETE FROM vec_fragment_memory WHERE id = %s", (f"frag_{fragment_id}",))
        logger.debug(f"VectorStore: 片段向量已删除 frag_{fragment_id}")

    def search_fragments(self, query: str, top_k: int = 5) -> list[SearchResult]:
        """语义检索知识片段。"""
        if not query.strip():
            return []

        query_embedding = self._embedding_fn([query[:300]])[0]
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT id, fragment_id, title, content,
                   1 - (embedding <=> %s::vector) AS score
            FROM vec_fragment_memory
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (_vec_to_str(query_embedding), _vec_to_str(query_embedding),
             min(top_k, 20)),
        )
        rows = cur.fetchall()

        search_results: list[SearchResult] = []
        for row in rows:
            search_results.append(
                SearchResult(
                    chunk_id=row["id"],
                    note_id=str(row["fragment_id"] or ""),
                    note_title=row["title"] or "知识片段",
                    content=row["content"] or "",
                    score=round(float(row["score"]), 4),
                    metadata={"fragment_id": row["fragment_id"], "title": row["title"]},
                )
            )
        return search_results

    # ---- 统计 ----

    def count(self) -> int:
        """返回存储的总分块数。"""
        cur = self._conn.cursor()
        cur.execute("SELECT COUNT(*) AS cnt FROM vec_note_chunks")
        return cur.fetchone()["cnt"]

    def list_note_ids(self) -> list[str]:
        """返回所有 note_id 的去重列表。"""
        cur = self._conn.cursor()
        cur.execute("SELECT DISTINCT note_id FROM vec_note_chunks")
        return [r["note_id"] for r in cur.fetchall()]


def _vec_to_str(vec: list[float]) -> str:
    """浮点列表 → pgvector 接受的字符串 '[1,2,3]'。"""
    return "[" + ",".join(f"{x:.7f}" for x in vec) + "]"
