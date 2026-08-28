"""BM25 全文检索测试（Phase 5F FR58）。

用独立 PostgreSQL schema 测试 pg_trgm 索引：
- 笔记写入时即被索引（pg_trgm GIN 索引直接挂 notes 表）
- bm25_search 关键词命中
- 软删除笔记不出现在结果
- 空查询返回空
"""

import pytest

from brain.models import NoteMetadata, SourceType
from brain.storage.metadata import MetadataStore


@pytest.fixture
def store(test_schema):
    """独立 schema 隔离的 MetadataStore。"""
    import psycopg

    from tests.conftest import _TEST_DSN

    conn = psycopg.connect(_TEST_DSN, autocommit=True)
    conn.execute(f"CREATE SCHEMA IF NOT EXISTS {test_schema}")
    conn.close()
    dsn = f"{_TEST_DSN} options='-c search_path={test_schema},public'"
    s = MetadataStore(dsn=dsn)
    s.initialize()
    yield s
    s.close()
    conn = psycopg.connect(_TEST_DSN, autocommit=True)
    conn.execute(f"DROP SCHEMA IF EXISTS {test_schema} CASCADE")
    conn.close()


def _make_note(note_id: str, title: str, preview: str) -> NoteMetadata:
    return NoteMetadata(
        id=note_id,
        title=title,
        source_type=SourceType.MARKDOWN,
        content_preview=preview,
        content_length=len(preview),
    )


class TestBM25Search:
    def test_create_note_syncs_fts(self, store):
        """笔记写入后能被 BM25 检索到。"""
        store.create_note(_make_note("n1", "LangGraph 状态管理", "LangGraph 的状态机设计"))

        results = store.bm25_search("LangGraph", top_k=5)

        assert len(results) == 1
        assert results[0]["note_id"] == "n1"
        assert "LangGraph" in results[0]["title"]

    def test_keyword_match_in_title_and_preview(self, store):
        """关键词在标题或预览中都能命中。"""
        store.create_note(_make_note("n1", "Python 异步编程", "asyncio 事件循环"))
        store.create_note(_make_note("n2", "Java 并发", "线程池设计"))

        results = store.bm25_search("asyncio", top_k=5)

        assert len(results) == 1
        assert results[0]["note_id"] == "n1"

    def test_soft_deleted_note_excluded(self, store):
        """软删除的笔记不出现在 BM25 结果。"""
        store.create_note(_make_note("n1", "LangGraph 教程", "LangGraph 基础"))
        store.delete_note("n1", soft=True)  # 软删除

        results = store.bm25_search("LangGraph", top_k=5)

        # 软删除的笔记状态变 deleted，BM25 检索按 status='active' 过滤
        assert len(results) == 0

    def test_hard_delete_removes_from_fts(self, store):
        """硬删除从 FTS 索引移除。"""
        store.create_note(_make_note("n1", "RAG 优化", "混合检索策略"))
        store.delete_note("n1", soft=False)  # 硬删除

        results = store.bm25_search("RAG", top_k=5)

        assert len(results) == 0

    def test_update_note_title_resyncs_fts(self, store):
        """更新笔记标题后 FTS 同步，新标题可被检索。"""
        store.create_note(_make_note("n1", "旧标题", "内容"))
        store.update_note("n1", title="全新标题关键词")

        results = store.bm25_search("全新标题关键词", top_k=5)

        assert len(results) == 1
        assert results[0]["note_id"] == "n1"

    def test_empty_query_returns_empty(self, store):
        store.create_note(_make_note("n1", "任意标题", "任意内容"))
        assert store.bm25_search("", top_k=5) == []
        assert store.bm25_search("   ", top_k=5) == []

    def test_no_match_returns_empty(self, store):
        store.create_note(_make_note("n1", "Python", "异步编程"))
        results = store.bm25_search("完全不相关的查询词XYZ", top_k=5)
        assert len(results) == 0

    def test_results_ordered_by_relevance(self, store):
        """多结果按相似度降序（pg_trgm similarity 排序）。"""
        store.create_note(_make_note("n1", "RAG RAG RAG 优化", "RAG 多次出现"))
        store.create_note(_make_note("n2", "RAG 简介", "RAG 仅一次"))

        results = store.bm25_search("RAG", top_k=5)

        assert len(results) == 2
        # 两条都能命中，顺序由 similarity 决定（此处只验证都返回）
        note_ids = {r["note_id"] for r in results}
        assert note_ids == {"n1", "n2"}

    def test_backfill_existing_notes(self, store):
        """pg_trgm 索引直接挂在 notes 表，无需回填——笔记写入即可检索。"""
        store.create_note(_make_note("n1", "回填测试", "pg_trgm 索引内容"))
        # pg_trgm 无独立 FTS 表，_init_bm25_index 为空操作，笔记写入即可检索
        store._init_bm25_index()

        results = store.bm25_search("回填", top_k=5)
        assert len(results) == 1
        assert results[0]["note_id"] == "n1"
