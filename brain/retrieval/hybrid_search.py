"""混合检索 + RRF 融合（Phase 5F FR58）。

把纯向量召回升级为「BM25 + 向量 + RRF 融合」：
  - 向量召回（VectorStore.search）：语义相似，擅长同义/改写命中
  - BM25 召回（MetadataStore.bm25_search）：关键词精确命中，擅长专有名词/标识符
  - RRF 融合：两路结果按排名倒数加权，兼顾语义和关键词

降级链（任一环节失败不阻塞）：
  - 查询改写失败 → 仅用原 query
  - BM25 失败 → 仅向量召回
  - Rerank 失败/关闭 → 用 RRF 融合后的原序
"""

from loguru import logger

from brain.config import get_config
from brain.models import SearchResult
from brain.storage.metadata import MetadataStore
from brain.storage.vector_store import VectorStore


class HybridSearcher:
    """混合检索器——统一 BM25 + 向量 + RRF + Rerank + 查询改写。

    双调用方统一入口：
      - researcher.search_notes 工具
      - server /api/search
    """

    def __init__(
        self,
        vector_store: VectorStore,
        metadata_store: MetadataStore,
        reranker=None,
        rewriter=None,
    ):
        self._vector_store = vector_store
        self._metadata_store = metadata_store
        self._reranker = reranker
        self._rewriter = rewriter
        cfg = get_config().retrieval
        self._hybrid_enabled = cfg.hybrid_enabled
        self._rrf_k = cfg.rrf_k
        self._candidate_top_n = cfg.candidate_top_n

    def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        """混合检索主入口。

        Args:
            query: 用户查询
            top_k: 最终返回数量

        Returns:
            按 RRF 融合分（或 rerank 分）降序的结果列表
        """
        if not query.strip():
            return []

        # 1. 查询改写（可选）——失败降级为 [query]
        if self._rewriter:
            queries = self._rewriter.rewrite(query)
        else:
            queries = [query]

        # 2. 多路召回 + RRF 融合
        candidates = self._retrieve_and_fuse(queries, top_n=self._candidate_top_n)

        # 3. Rerank 精排（可选）——用原始 query 精排，失败降级为原序
        if self._reranker:
            final = self._reranker.rerank(query, candidates, top_k=top_k)
        else:
            final = candidates[:top_k]

        return final

    def _retrieve_and_fuse(self, queries: list[str], top_n: int) -> list[SearchResult]:
        """对多个查询执行向量+BM25 召回，RRF 融合后返回 Top-N。

        去重粒度：note_id（同一笔记多 chunk 命中只取最高分 chunk 代表）。
        """
        # 收集每路结果及其排名
        # rank_map: note_id -> {"result": SearchResult, "ranks": [rank_v, rank_b, ...]}
        rank_map: dict[str, dict] = {}

        for q in queries:
            # 向量召回（每个 query 召回更多候选供融合）
            vector_results = self._vector_store.search(q, top_k=max(top_n * 2, 20))
            self._collect_ranks(vector_results, rank_map, "vector")

            # BM25 召回（可选，失败降级为仅向量）
            if self._hybrid_enabled:
                try:
                    bm25_rows = self._metadata_store.bm25_search(q, top_k=max(top_n * 2, 20))
                except Exception as e:
                    logger.warning(f"[hybrid] BM25 召回失败，仅用向量: {e}")
                    bm25_rows = []
                bm25_results = self._bm25_rows_to_results(bm25_rows, vector_results)
                self._collect_ranks(bm25_results, rank_map, "bm25")

        # RRF 融合：score = Σ 1/(k + rank_i)
        fused: list[tuple[float, SearchResult]] = []
        for _note_id, entry in rank_map.items():
            rrf_score = sum(1.0 / (self._rrf_k + r) for r in entry["ranks"])
            result = entry["result"]
            fused.append(
                (
                    rrf_score,
                    SearchResult(
                        chunk_id=result.chunk_id,
                        note_id=result.note_id,
                        note_title=result.note_title,
                        content=result.content,
                        score=round(rrf_score, 6),
                        metadata={**result.metadata, "fused": True},
                    ),
                )
            )

        # 按 RRF 分降序取 Top-N
        fused.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in fused[:top_n]]

    @staticmethod
    def _collect_ranks(
        results: list[SearchResult],
        rank_map: dict[str, dict],
        source: str,
    ) -> None:
        """把单路结果按 note_id 收集进 rank_map，记录排名（从 1 开始）。

        同一 note_id 多 chunk 命中时，保留分数最高（排名最前）的那个 chunk。
        """
        seen_notes: set[str] = set()
        for rank, result in enumerate(results, start=1):
            if not result.note_id or result.note_id in seen_notes:
                continue
            seen_notes.add(result.note_id)
            entry = rank_map.setdefault(
                result.note_id,
                {"result": result, "ranks": []},
            )
            entry["ranks"].append(rank)
            # 保留分数更高的 chunk 作为代表（排名更前的已先入，这里不覆盖）

    @staticmethod
    def _bm25_rows_to_results(
        bm25_rows: list[dict],
        vector_results: list[SearchResult],
    ) -> list[SearchResult]:
        """把 BM25 查询结果（dict）转为 SearchResult。

        BM25 命中的是笔记级（note_id + title + preview），无 chunk 级信息。
        尝试从同批向量结果中匹配同 note_id 的 chunk 内容；匹配不到则用 preview。
        """
        # 建立 note_id -> chunk content 的映射（向量结果里有完整 chunk 内容）
        vector_content_map: dict[str, str] = {}
        for vr in vector_results:
            if vr.note_id and vr.note_id not in vector_content_map:
                vector_content_map[vr.note_id] = vr.content

        results: list[SearchResult] = []
        for row in bm25_rows:
            note_id = row.get("note_id", "")
            content = vector_content_map.get(note_id, row.get("content_preview", ""))
            results.append(
                SearchResult(
                    chunk_id=f"bm25_{note_id}",
                    note_id=note_id,
                    note_title=row.get("title", "无标题"),
                    content=content,
                    score=float(row.get("score", 0.0)),
                    metadata={"source": "bm25"},
                )
            )
        return results
