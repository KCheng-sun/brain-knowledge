"""Reranker 单元测试（Phase 5F FR59）。

mock SiliconFlow /v1/rerank API 响应，覆盖：
- 正常精排：按 relevance_score 重排
- 失败降级：API 异常时原序返回
"""

from unittest.mock import MagicMock, patch

from brain.models import SearchResult
from brain.retrieval.reranker import Reranker


def _make_result(note_id: str, content: str, score: float) -> SearchResult:
    return SearchResult(
        chunk_id=f"chunk_{note_id}",
        note_id=note_id,
        note_title=note_id,
        content=content,
        score=score,
        metadata={},
    )


class TestReranker:
    def test_normal_rerank_reorders_by_relevance(self):
        """正常情况：按 relevance_score 降序重排候选。"""
        reranker = Reranker(api_key="fake", base_url="https://fake/v1")
        candidates = [
            _make_result("A", "内容A", 0.9),
            _make_result("B", "内容B", 0.8),
            _make_result("C", "内容C", 0.7),
        ]

        # mock API 返回：B 最相关，A 次之，C 最后
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {"index": 1, "relevance_score": 0.95},  # B
                {"index": 0, "relevance_score": 0.80},  # A
                {"index": 2, "relevance_score": 0.60},  # C
            ]
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(reranker, "_api_key", "fake"), \
             patch("openai.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_openai.return_value = mock_client
            mock_client._client.post.return_value = mock_response

            results = reranker.rerank("查询", candidates, top_k=3)

        # 应按 relevance_score 降序：B, A, C
        assert [r.note_id for r in results] == ["B", "A", "C"]
        # score 被替换为 rerank 分
        assert results[0].score == 0.95
        assert results[0].metadata.get("reranked") is True

    def test_failure_degrades_to_original_order(self):
        """API 异常时降级为原序返回 top_k。"""
        reranker = Reranker(api_key="fake", base_url="https://fake/v1")
        candidates = [
            _make_result("A", "内容A", 0.9),
            _make_result("B", "内容B", 0.8),
        ]

        with patch("openai.OpenAI", side_effect=RuntimeError("网络错误")):
            results = reranker.rerank("查询", candidates, top_k=2)

        # 原序返回，不抛异常
        assert [r.note_id for r in results] == ["A", "B"]

    def test_empty_candidates_returns_empty(self):
        reranker = Reranker(api_key="fake", base_url="https://fake/v1")
        assert reranker.rerank("查询", [], top_k=5) == []

    def test_empty_query_returns_candidates_as_is(self):
        """空查询直接返回原序，不调 API。"""
        reranker = Reranker(api_key="fake", base_url="https://fake/v1")
        candidates = [_make_result("A", "内容A", 0.9)]

        with patch("openai.OpenAI") as mock_openai:
            results = reranker.rerank("   ", candidates, top_k=5)
            # 不应调用 API
            mock_openai.return_value._client.post.assert_not_called()

        assert results == candidates[:5]
