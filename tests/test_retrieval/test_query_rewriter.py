"""QueryRewriter 单元测试（Phase 5F FR60）。

mock LLM 响应，覆盖：
- 正常改写：解析多行结果，去重保序
- 编号前缀清理
- 失败降级为仅原始查询
"""

from unittest.mock import MagicMock

from brain.retrieval.query_rewriter import QueryRewriter


class TestQueryRewriter:
    def test_normal_rewrite_returns_original_plus_versions(self):
        """正常改写：返回 [原始查询, 改写1, 改写2, ...]。"""
        llm = MagicMock()
        llm.invoke.return_value = MagicMock(
            content="RAG 优化策略\n检索增强生成方法\n如何提升 RAG 效果"
        )
        rewriter = QueryRewriter(llm=llm, count=3)

        results = rewriter.rewrite("RAG 优化")

        # 首位是原始查询
        assert results[0] == "RAG 优化"
        # 后续是改写版本
        assert "RAG 优化策略" in results
        assert len(results) == 4  # 原始 + 3 改写

    def test_strips_numeric_prefixes(self):
        """改写结果带编号前缀（1. 2.）时应清理。"""
        llm = MagicMock()
        llm.invoke.return_value = MagicMock(
            content="1. RAG 优化策略\n2) 检索增强生成\n3、如何提升 RAG"
        )
        rewriter = QueryRewriter(llm=llm, count=3)

        results = rewriter.rewrite("RAG")

        assert "1. RAG 优化策略" not in results
        assert "RAG 优化策略" in results
        assert "检索增强生成" in results

    def test_dedup_identical_rewrites(self):
        """重复的改写版本去重。"""
        llm = MagicMock()
        llm.invoke.return_value = MagicMock(
            content="RAG 优化\nRAG 优化\nRAG 优化"
        )
        rewriter = QueryRewriter(llm=llm, count=3)

        results = rewriter.rewrite("RAG")

        # 原始 + 去重后只剩 1 个不同改写
        assert len(results) == 2

    def test_failure_degrades_to_original_only(self):
        """LLM 异常时降级为仅 [原始查询]。"""
        llm = MagicMock()
        llm.invoke.side_effect = RuntimeError("API 错误")
        rewriter = QueryRewriter(llm=llm, count=3)

        results = rewriter.rewrite("RAG 优化")

        assert results == ["RAG 优化"]

    def test_empty_query_returns_self(self):
        rewriter = QueryRewriter(llm=MagicMock(), count=3)
        assert rewriter.rewrite("") == [""]
        assert rewriter.rewrite("   ") == ["   "]

    def test_limits_to_count_versions(self):
        """改写版本数不超过 count。"""
        llm = MagicMock()
        llm.invoke.return_value = MagicMock(
            content="版本1\n版本2\n版本3\n版本4\n版本5"
        )
        rewriter = QueryRewriter(llm=llm, count=2)

        results = rewriter.rewrite("原始")

        # 原始 + 最多 2 个改写
        assert len(results) == 3
        assert results[0] == "原始"
