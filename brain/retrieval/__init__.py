"""检索层（Phase 5F RAG 质量增强）。

混合检索 = BM25 + 向量 + RRF 融合，可选 Rerank 精排和查询改写。
"""

import os

from brain.retrieval.hybrid_search import HybridSearcher
from brain.retrieval.query_rewriter import QueryRewriter
from brain.retrieval.reranker import Reranker

__all__ = ["HybridSearcher", "Reranker", "QueryRewriter", "build_hybrid_searcher"]


def build_hybrid_searcher(vector_store, metadata_store) -> HybridSearcher:
    """根据 config 组装混合检索链路（CLI/server/eval 共用）。

    各环节按 config 开关启用，失败降级不阻塞。
    """
    from brain.config import get_config

    cfg = get_config()
    reranker = None
    if cfg.retrieval.rerank_enabled:
        reranker = Reranker(
            api_key=cfg.embedding.api_key or os.environ.get("SILICONFLOW_API_KEY", ""),
            base_url=cfg.embedding.base_url,
            model=cfg.retrieval.rerank_model,
        )
    rewriter = None
    if cfg.retrieval.query_rewrite_enabled:
        rewriter = QueryRewriter(count=cfg.retrieval.query_rewrite_count)
    return HybridSearcher(
        vector_store=vector_store,
        metadata_store=metadata_store,
        reranker=reranker,
        rewriter=rewriter,
    )
