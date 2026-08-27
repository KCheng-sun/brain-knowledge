"""BM25 全文检索测试（Phase 5F FR58）。

用临时 SQLite 测试 FTS5 索引：
- 笔记写入时同步 FTS
- bm25_search 关键词命中
- 软删除笔记不出现在结果
- 空查询返回空
"""

import pytest

from brain.models import NoteMetadata, SourceType
from brain.storage.metadata import MetadataStore


@pytest.fixture
def store(tmp_path, monkeypatch):
    """临时 SQLite MetadataStore（强制 SQLite，忽略 .env 的 MySQL 配置）。"""
    import brain.config as config_module

    cfg = config_module.get_config()
    monkeypatch.setattr(cfg.database, "host", None)

    s = MetadataStore(db_path=tmp_path / "test.db")
    s.initialize()
    yield s
    s.close()


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
        """多结果按 BM25 相关性降序。"""
        store.create_note(_make_note("n1", "RAG RAG RAG 优化", "RAG 多次出现"))
        store.create_note(_make_note("n2", "RAG 简介", "RAG 仅一次"))

        results = store.bm25_search("RAG", top_k=5)

        assert len(results) == 2
        # 出现次数更多的应排前面（BM25 词频权重）
        assert results[0]["note_id"] == "n1"

    def test_backfill_existing_notes(self, store):
        """旧库升级时 FTS 回填已存在的笔记（_init_bm25_index 逻辑）。"""
        # 先写入笔记
        store.create_note(_make_note("n1", "回填测试", "FTS 回填内容"))
        # 手动清空 FTS 模拟旧库
        store._exec("DELETE FROM notes_fts")
        # 重新运行回填
        store._init_bm25_index()

        results = store.bm25_search("回填", top_k=5)
        assert len(results) == 1
        assert results[0]["note_id"] == "n1"
