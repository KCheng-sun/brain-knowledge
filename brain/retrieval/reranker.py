"""Rerank 精排（Phase 5F FR59）。

调用 SiliconFlow /v1/rerank API（BAAI/bge-reranker-v2-m3）对候选结果精排。
复用现有 SILICONFLOW_API_KEY，零新依赖。
失败时降级为原序返回（不阻塞主流程）。
"""

from loguru import logger

from brain.models import SearchResult


class Reranker:
    """Cross-Encoder 精排——对召回的候选结果按相关性重排。

    SiliconFlow rerank API 接口：
        POST {base_url}/rerank
        body: {model, query, documents, top_n, return_documents: false}
        resp: {results: [{index, relevance_score}, ...]}
    """

    def __init__(self, api_key: str, base_url: str, model: str = "BAAI/bge-reranker-v2-m3"):
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model

    def rerank(
        self,
        query: str,
        candidates: list[SearchResult],
        top_k: int,
    ) -> list[SearchResult]:
        """对候选结果精排，返回 Top-K。

        Args:
            query: 用户原始查询（用原始 query，非改写版本）
            candidates: 召回+融合后的候选列表
            top_k: 返回数量

        Returns:
            按 relevance_score 降序的 Top-K 结果；失败时返回原序 Top-K（降级）
        """
        if not candidates:
            return []

        if not query.strip():
            return candidates[:top_k]

        try:
            from openai import OpenAI

            # SiliconFlow 兼容 OpenAI SDK，但 rerank 是独立端点，用底层 post
            client = OpenAI(api_key=self._api_key, base_url=self._base_url)
            # 截断每个候选文本，防超 API 长度限制
            documents = [c.content[:500] for c in candidates]

            # OpenAI SDK 不直接支持 /rerank，用 _client.post 走原始 HTTP
            response = client._client.post(
                f"{self._base_url}/rerank",
                json={
                    "model": self._model,
                    "query": query[:500],
                    "documents": documents,
                    "top_n": top_k,
                    "return_documents": False,
                },
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
            response.raise_for_status()
            data = response.json()

            results = data.get("results", [])
            # 按 relevance_score 降序（API 可能已排序，但显式排一次更稳）
            results.sort(key=lambda r: r.get("relevance_score", 0), reverse=True)

            reranked: list[SearchResult] = []
            for r in results[:top_k]:
                idx = r.get("index")
                if idx is None or idx >= len(candidates):
                    continue
                candidate = candidates[idx]
                # 用 rerank 分数覆盖原 score（归一化到 0~1）
                score = float(r.get("relevance_score", candidate.score))
                reranked.append(
                    SearchResult(
                        chunk_id=candidate.chunk_id,
                        note_id=candidate.note_id,
                        note_title=candidate.note_title,
                        content=candidate.content,
                        score=round(min(max(score, 0.0), 1.0), 4),
                        metadata={**candidate.metadata, "reranked": True},
                    )
                )
            logger.debug(f"[reranker] ✓ 精排完成: {len(reranked)}/{len(candidates)} 候选")
            return reranked

        except Exception as e:
            logger.warning(f"[reranker] ⚠ 精排失败，降级为原序: {e}")
            return candidates[:top_k]
