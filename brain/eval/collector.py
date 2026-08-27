"""Bad Case 收集器（Phase 5D FR54）。

收集失败/点踩/空回答的问答，写入数据库 bad_cases 表，
页面可查看/删除/一键转为 golden case。
"""

from __future__ import annotations

from typing import Any

from loguru import logger


def collect_bad_case(
    metadata_store,
    trace_id: str | None,
    question: str,
    answer: str,
    reason: str,
    extra: dict[str, Any] | None = None,
) -> None:
    """收集一条 bad case 到数据库。

    失败不抛异常（不影响主流程）。

    Args:
        metadata_store: MetadataStore 实例
        trace_id: 关联的 trace_id（便于回溯调用链）
        question: 用户问题
        answer: Agent 回答
        reason: 收集原因 'user_thumbs_down'|'empty_answer'|'error'|'recursion_limit'
        extra: 附加信息（如错误详情）
    """
    try:
        metadata_store.add_bad_case(
            trace_id=trace_id,
            question=question,
            answer=answer,
            reason=reason,
            extra=extra,
        )
        logger.info(f"已收集 bad case (reason={reason}, trace={trace_id})")
    except Exception as e:
        # bad case 收集失败不应影响主流程
        logger.warning(f"收集 bad case 失败: {e}")
