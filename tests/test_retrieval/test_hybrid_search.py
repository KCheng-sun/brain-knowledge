"""HybridSearcher 单元测试（Phase 5F FR58）。

覆盖：
- RRF 融合公式：两路结果按排名倒数加权
- note_id 粒度去重：同笔记多 chunk 只取最高分
- 降级：BM25 失败时仅向量召回
- BM25 rows → SearchResult 转换
"""

from unittest.mock import MagicMock

import pytest

from brain.models import SearchResult
from brain.retrieval.hybrid_search import HybridSearcher


def _make_result(note_id: str, title: str, content: str, score: float) -> SearchResult:
    """构造测试用 SearchResult。"""
    return SearchResult(
        chunk_id=f"chunk_{note_id}",
        note_id=note_id,
        note_title=title,
        content=content,
        score=score,
        metadata={},
    )


@pytest.fixture
def mock_stores():
    """构造 mock VectorStore 和 MetadataStore。"""
    vs = MagicMock()
    ms = MagicMock()
    return vs, ms


@pytest.fixture
def searcher(mock_stores):
    """构造无 reranker/rewriter 的 HybridSearcher（纯 RRF 融合）。"""
    vs, ms = mock_stores
    # 关闭查询改写，避免触发 LLM
    import brain.config as config_module

    cfg = config_module.get_config()
    original = cfg.retrieval.query_rewrite_enabled
    cfg.retrieval.query_rewrite_enabled = False
    s = HybridSearcher(vector_store=vs, metadata_store=ms)
    yield s
    cfg.retrieval.query_rewrite_enabled = original


class TestRRFFusion:
    """RRF 融合逻辑测试。"""

    def test_vector_and_bm25_both_hit_same_note_ranks_higher(
        self, searcher, mock_stores
    ):
        """同一笔记在两路都命中，RRF 分应高于只在一路命中的笔记。"""
        vs, ms = mock_stores
        # 向量召回：noteA 第1，noteB 第2
        vs.search.return_value = [
            _make_result("noteA", "A", "内容A", 0.9),
            _make_result("noteB", "B", "内容B", 0.8),
        ]
        # BM25 召回：noteA 第1，noteC 第2
        ms.bm25_search.return_value = [
            {"note_id": "noteA", "score": 5.0, "title": "A", "content_preview": "预览A"},
            {"note_id": "noteC", "score": 3.0, "title": "C", "content_preview": "预览C"},
        ]

        results = searcher.search("查询", top_k=3)

        # noteA 两路都命中（rank1+rank1），RRF 分最高
        assert results[0].note_id == "noteA"
        # noteA 的 RRF 分 = 1/(60+1) + 1/(60+1) ≈ 0.0328
        assert results[0].score == pytest.approx(2 * (1 / 61), abs=0.001)
        # noteB/noteC 只一路命中，分较低
        note_ids = [r.note_id for r in results]
        assert "noteB" in note_ids and "noteC" in note_ids

    def test_dedup_by_note_id(self, searcher, mock_stores):
        """同一笔记多 chunk 命中时去重，只保留一个代表。"""
        vs, ms = mock_stores
        vs.search.return_value = [
            _make_result("noteA", "A", "chunk1", 0.9),
            _make_result("noteA", "A", "chunk2", 0.85),  # 同 noteA 不同 chunk
            _make_result("noteB", "B", "chunkB", 0.7),
        ]
        ms.bm25_search.return_value = []

        results = searcher.search("查询", top_k=5)

        # noteA 只出现一次（去重）
        note_ids = [r.note_id for r in results]
        assert note_ids.count("noteA") == 1
        assert len(results) == 2  # noteA + noteB

    def test_bm25_failure_degrades_to_vector_only(self, searcher, mock_stores):
        """BM25 抛异常时降级为纯向量召回，不阻塞。"""
        vs, ms = mock_stores
        vs.search.return_value = [
            _make_result("noteA", "A", "内容A", 0.9),
        ]
        ms.bm25_search.side_effect = RuntimeError("FTS 表不存在")

        results = searcher.search("查询", top_k=5)

        # 仍返回向量结果，未抛异常
        assert len(results) == 1
        assert results[0].note_id == "noteA"


class TestBM25RowsConversion:
    """BM25 dict 结果转 SearchResult 测试。"""

    def test_bm25_row_uses_vector_content_when_available(self, searcher, mock_stores):
        """BM25 命中的笔记若在向量结果中也有，复用其 chunk 内容。"""
        vs, ms = mock_stores
        vs.search.return_value = [
            _make_result("noteA", "A", "完整chunk内容", 0.9),
        ]
        ms.bm25_search.return_value = [
            {"note_id": "noteA", "score": 5.0, "title": "A", "content_preview": "短预览"},
        ]

        results = searcher.search("查询", top_k=5)

        note_a = next(r for r in results if r.note_id == "noteA")
        # 应使用向量结果里的完整 chunk 内容，而非 BM25 的短预览
        assert "完整chunk内容" in note_a.content

    def test_bm25_only_note_uses_preview(self, searcher, mock_stores):
        """BM25 独占命中的笔记（向量没召回）用 content_preview。"""
        vs, ms = mock_stores
        vs.search.return_value = []  # 向量无结果
        ms.bm25_search.return_value = [
            {"note_id": "noteX", "score": 5.0, "title": "X", "content_preview": "BM25预览内容"},
        ]

        results = searcher.search("查询", top_k=5)

        assert len(results) == 1
        assert results[0].note_id == "noteX"
        assert "BM25预览内容" in results[0].content


class TestEmptyQuery:
    """空查询处理。"""

    def test_empty_query_returns_empty(self, searcher):
        """空查询返回空列表，不调用任何检索。"""
        results = searcher.search("", top_k=5)
        assert results == []

    def test_whitespace_query_returns_empty(self, searcher):
        results = searcher.search("   ", top_k=5)
        assert results == []
