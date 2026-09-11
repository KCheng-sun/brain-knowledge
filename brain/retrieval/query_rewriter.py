"""查询改写（Phase 5F FR60）。

Multi-Query 策略：用 LLM 生成多个语义等价但用词不同的查询版本，
多路召回后去重融合，提升语义覆盖率。
复用主 LLM（DeepSeek），提示词存 prompts 表（key=query_rewriter）。
失败时降级为仅用原查询（不阻塞主流程）。
"""

from loguru import logger

from brain.llm import get_chat_model
from brain.prompts import get_prompt_template


class QueryRewriter:
    """Multi-Query 查询改写器。

    生成 count 个改写版本 + 原始查询，共 count+1 路召回。
    """

    def __init__(self, llm=None, count: int = 3):
        self._llm = llm  # 懒加载：为 None 时首次 rewrite 才调 get_chat_model()
        self._count = count

    def rewrite(self, query: str) -> list[str]:
        """生成改写查询列表（含原始查询，位于首位）。

        Args:
            query: 用户原始查询

        Returns:
            [原始查询, 改写1, 改写2, ...]；失败时返回 [query]
        """
        if not query.strip():
            return [query]

        try:
            from langchain_core.messages import HumanMessage

            # 懒加载 LLM（构建时不初始化，避免测试/无 key 环境报错）
            if self._llm is None:
                self._llm = get_chat_model()

            # 提示词从 prompts 表读取（is_template=1，含 {query}/{count} 占位符）
            prompt = get_prompt_template("query_rewriter", query=query, count=self._count)
            # Phase 5G：Langfuse 追踪查询改写（直接 LLM 调用，用上下文管理器建 trace）
            from brain.langfuse_tracing import langfuse_trace
            with langfuse_trace("query-rewrite", tags=["rag", "retrieval"]) as lf:
                response = self._llm.invoke(
                    [HumanMessage(content=prompt)], config=lf.langchain_config()
                )
            lines = [
                line.strip()
                for line in response.content.split("\n")
                if line.strip()
            ]
            # 过滤掉可能的编号前缀（"1." "2)" 等）
            import re

            cleaned = [re.sub(r"^[\d]+[.)、]\s*", "", line) for line in lines]
            # 去重保序，最多取 count 个改写
            seen = set()
            rewrites = []
            for r in cleaned:
                if r and r not in seen and r != query:
                    seen.add(r)
                    rewrites.append(r)
                if len(rewrites) >= self._count:
                    break

            logger.debug(f"[rewriter] ✓ 改写 {len(rewrites)} 版本: {rewrites}")
            return [query] + rewrites

        except Exception as e:
            logger.warning(f"[rewriter] ⚠ 改写失败，降级为仅原始查询: {e}")
            return [query]
