"""LLM-as-Judge 评估器（Phase 5D FR55）。

用 DeepSeek 当裁判，对问答抽样打分（1-5 分 + 维度 + 评语）。
成本可控：抽样 + 单次 Judge 调用。
提示词从 prompts 表读取（Phase 5E），key="judge"。
"""

from __future__ import annotations

import json
from typing import Any

from loguru import logger

from brain.prompts import get_prompt_template


class LLMJudge:
    """LLM-as-Judge 评估器。

    用法::

        judge = LLMJudge(metadata_store)
        result = judge.judge("问题", "回答", "参考片段")
    """

    def __init__(self, metadata_store, llm=None):
        self._ms = metadata_store
        self._llm = llm  # 可注入，默认懒加载

    def _get_llm(self):
        if self._llm is None:
            from brain.llm import get_chat_model

            self._llm = get_chat_model()
        return self._llm

    def judge(
        self,
        question: str,
        answer: str,
        context: str = "",
        trace_id: str | None = None,
        run_id: int | None = None,
    ) -> dict[str, Any]:
        """对单条问答打分。

        Args:
            question: 用户问题
            answer: Agent 回答
            context: 知识库相关片段（可空）
            trace_id: 关联 trace_id
            run_id: 关联评估批次 ID

        Returns:
            {"score": 1-5, "dimensions": {...}, "comment": "..."}
            失败时返回 {"score": 0, "error": "..."}
        """
        prompt = get_prompt_template(
            "judge",
            question=question[:500],
            answer=answer[:2000],
            context=context[:1000] or "（无参考片段）",
        )

        try:
            from langchain_core.messages import HumanMessage, SystemMessage

            llm = self._get_llm()
            # 拆分 system / user：提示词用 ---USER--- 标记边界
            if "---USER---" in prompt:
                sys_text, user_text = prompt.split("---USER---", 1)
                messages = [
                    SystemMessage(content=sys_text.strip()),
                    HumanMessage(content=user_text.strip()),
                ]
            else:
                # 兼容旧格式（无分隔符）
                messages = [HumanMessage(content=prompt)]
            response = llm.invoke(messages)
            text = response.content if hasattr(response, "content") else str(response)

            # 解析 JSON（LLM 可能输出多余文本，提取第一个 JSON 块）
            result = self._parse_judge_response(text)

            # 写入 eval_scores 表
            self._ms.add_eval_score(
                trace_id=trace_id,
                question=question,
                answer=answer,
                score=result["score"],
                dimensions=result.get("dimensions"),
                comment=result.get("comment"),
                run_id=run_id,
            )

            logger.info(
                f"LLM-Judge 打分: {result['score']}/5 "
                f"(trace={trace_id}, comment={result.get('comment', '')[:30]})"
            )
            return result

        except Exception as e:
            logger.error(f"LLM-Judge 打分失败: {e}")
            return {"score": 0, "error": str(e)[:200]}

    def _parse_judge_response(self, text: str) -> dict[str, Any]:
        """解析 LLM 返回的 JSON（容错处理）。"""
        # 尝试直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 尝试提取 { ... } 块
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass

        # 解析失败，返回默认
        logger.warning(f"LLM-Judge 响应解析失败: {text[:100]}")
        return {"score": 0, "comment": "解析失败", "raw": text[:200]}

    def judge_recent_traces(self, sample_rate: float = 0.1, limit: int = 20) -> list[dict]:
        """对最近的问答 trace 抽样打分。

        Args:
            sample_rate: 抽样比例（默认 10%）
            limit: 最多评估多少条

        Returns:
            打分结果列表
        """
        import random

        # 取最近的 ask trace，排除离线评估自身产生的 trace（eval_ 开头）
        all_traces = self._ms.get_recent_traces(limit=limit * 5)
        traces = [t for t in all_traces if not t["trace_id"].startswith("eval_")]
        if not traces:
            logger.info("无可用 trace（已排除评估自身），跳过 Judge 评估")
            return []

        # 抽样：trace 少时保证最少 3 条（或全部，如果总数<5）
        if len(traces) < 5:
            sampled = traces  # 太少就全评
        else:
            sample_size = max(3, int(len(traces) * sample_rate))
            sampled = random.sample(traces, min(sample_size, limit))

        # 创建评估批次
        import time
        t0 = time.perf_counter()
        run_id = self._ms.add_eval_run(run_type="judge", total=0)

        results = []
        for t in sampled:
            trace_id = t["trace_id"]
            # 从 trace_events 提取问答内容
            events = self._ms.get_trace_events(trace_id)
            # 找 llm_end 的 output 作为回答，tool 的 output 拼接为 context
            answer = ""
            context_parts = []
            for e in events:
                if e["event_type"] == "llm" and e.get("output"):
                    answer = e["output"]  # 取最后一个 llm 输出作为最终回答
                elif e["event_type"] == "tool" and e.get("output"):
                    context_parts.append(e["output"][:200])

            if not answer:
                continue

            # 从 metrics 提取问题（ask count 的 metadata）
            metrics = self._ms.get_trace_detail(trace_id)
            question = ""
            for m in metrics:
                if m["metric_type"] == "ask" and m.get("metadata", {}).get("question"):
                    question = m["metadata"]["question"]
                    break

            if not question:
                question = "（未知问题）"

            result = self.judge(
                question=question,
                answer=answer,
                context="\n---\n".join(context_parts[:3]),  # 最多 3 个片段
                trace_id=trace_id,
                run_id=run_id,
            )
            result["trace_id"] = trace_id
            results.append(result)

        # 更新批次记录——存完整结果供历史查看
        valid = [r for r in results if r.get("score", 0) > 0]
        avg = sum(r["score"] for r in valid) / len(valid) if valid else 0
        duration_ms = round((time.perf_counter() - t0) * 1000, 0)
        judge_details = [
            {
                "trace_id": r.get("trace_id", ""),
                "score": r.get("score", 0),
                "dimensions": r.get("dimensions"),
                "comment": r.get("comment", ""),
                "error": r.get("error"),
            }
            for r in results
        ]
        self._ms.update_eval_run(
            run_id, total=len(results), avg_score=round(avg, 2),
            duration_ms=duration_ms,
            details={"results": judge_details},
        )

        return results
