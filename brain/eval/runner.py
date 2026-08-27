"""离线评估运行器（Phase 5D FR53）。

加载 Golden Dataset，逐条跑问答，规则打分，生成报告。
评分维度：关键词命中(0.5) + 来源正确性(0.3) + 完整性(0.2)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from loguru import logger


@dataclass
class EvalCase:
    """单条评估用例。"""

    id: str
    question: str
    expected_keywords: list[str]
    expected_sources: list[str]
    min_score: float


@dataclass
class EvalResult:
    """单条评估结果。"""

    case: EvalCase
    answer: str
    score: float
    passed: bool
    details: dict[str, Any] = field(default_factory=dict)
    trace_id: str | None = None
    error: str | None = None


@dataclass
class EvalReport:
    """评估报告。"""

    total: int
    passed: int
    failed: int
    pass_rate: float
    avg_score: float
    results: list[EvalResult]
    started_at: str
    duration_ms: float

    def summary(self) -> str:
        """生成文本摘要。"""
        lines = [
            f"评估报告：{self.passed}/{self.total} 通过（通过率 {self.pass_rate:.1%}）",
            f"平均分：{self.avg_score:.3f}",
            f"耗时：{self.duration_ms:.0f}ms",
        ]
        if self.failed:
            lines.append(f"\n失败用例（{self.failed} 条）：")
            for r in self.results:
                if not r.passed:
                    lines.append(
                        f"  ❌ {r.case.id} [{r.case.question[:30]}] "
                        f"得分 {r.score:.3f}（阈值 {r.case.min_score}）"
                    )
                    if r.error:
                        lines.append(f"     错误: {r.error}")
                    else:
                        kw = r.details.get("keyword_score", 0)
                        src = r.details.get("source_score", 0)
                        comp = r.details.get("complete_score", 0)
                        lines.append(f"     关键词 {kw:.2f} / 来源 {src:.2f} / 完整性 {comp:.2f}")
        return "\n".join(lines)


class EvalRunner:
    """离线评估运行器。

    用法::

        runner = EvalRunner(vector_store, metadata_store)
        report = runner.run("tests/eval/golden_dataset.yaml")
        print(report.summary())
    """

    def __init__(self, vector_store, metadata_store):
        self._vs = vector_store
        self._ms = metadata_store

    def load_dataset(self, dataset_path: str | Path | None = None) -> list[EvalCase]:
        """加载 Golden Dataset。

        优先从数据库加载（页面管理的用例）；
        若传入 dataset_path（YAML），从文件加载（向后兼容 / 种子导入）。
        """

        if dataset_path is None:
            # 从数据库加载启用的 golden cases
            rows = self._ms.get_golden_cases(enabled_only=True)
            cases = [
                EvalCase(
                    id=r["id"],
                    question=r["question"],
                    expected_keywords=r.get("expected_keywords", []),
                    expected_sources=r.get("expected_sources", []),
                    min_score=float(r.get("min_score", 0.7)),
                )
                for r in rows
            ]
            logger.info(f"从数据库加载测试集: {len(cases)} 条用例")
            return cases

        # 从 YAML 文件加载（向后兼容）
        path = Path(dataset_path)
        if not path.exists():
            raise FileNotFoundError(f"测试集不存在: {path}")

        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or []

        cases = []
        for item in data:
            cases.append(
                EvalCase(
                    id=item["id"],
                    question=item["question"],
                    expected_keywords=item.get("expected_keywords", []),
                    expected_sources=item.get("expected_sources", []),
                    min_score=float(item.get("min_score", 0.7)),
                )
            )
        logger.info(f"加载测试集 {path.name}: {len(cases)} 条用例")
        return cases

    def run(
        self,
        dataset_path: str | Path | None = None,
        limit: int | None = None,
    ) -> EvalReport:
        """跑完整测试集，返回报告。

        Args:
            dataset_path: Golden Dataset 路径（None=从数据库加载，传入=从 YAML 加载）
            limit: 只跑前 N 条（调试用）
        """
        from brain.agents.researcher import ResearcherAgent
        from brain.observability import new_trace_id

        cases = self.load_dataset(dataset_path)
        if limit:
            cases = cases[:limit]

        agent = ResearcherAgent(self._vs, self._ms)
        results: list[EvalResult] = []
        start = datetime.now()

        for case in cases:
            logger.info(f"评估用例 {case.id}: {case.question[:40]}")
            trace_id = f"eval_{case.id}_{new_trace_id()}"

            try:
                answer = agent.research_sync(case.question, trace_id=trace_id)
                result = self._score(case, answer, trace_id)
            except Exception as e:
                logger.error(f"评估用例 {case.id} 失败: {e}")
                result = EvalResult(
                    case=case,
                    answer="",
                    score=0.0,
                    passed=False,
                    error=f"{type(e).__name__}: {e}",
                    trace_id=trace_id,
                )
            results.append(result)

        duration_ms = (datetime.now() - start).total_seconds() * 1000
        passed = sum(1 for r in results if r.passed)
        total = len(results)
        avg_score = sum(r.score for r in results) / total if total else 0

        return EvalReport(
            total=total,
            passed=passed,
            failed=total - passed,
            pass_rate=passed / total if total else 0,
            avg_score=avg_score,
            results=results,
            started_at=start.isoformat(),
            duration_ms=duration_ms,
        )

    def _score(self, case: EvalCase, answer: str, trace_id: str) -> EvalResult:
        """对单条问答打分。"""
        # 维度 1：关键词命中（0.5）
        keyword_score = self._score_keywords(case.expected_keywords, answer)

        # 维度 2：来源正确性（0.3）
        source_score = self._score_sources(case.expected_sources, trace_id)

        # 维度 3：完整性（0.2）
        complete_score = self._score_completeness(answer)

        score = 0.5 * keyword_score + 0.3 * source_score + 0.2 * complete_score
        passed = score >= case.min_score

        return EvalResult(
            case=case,
            answer=answer,
            score=round(score, 3),
            passed=passed,
            details={
                "keyword_score": round(keyword_score, 3),
                "source_score": round(source_score, 3),
                "complete_score": round(complete_score, 3),
                "hit_keywords": [k for k in case.expected_keywords if k in answer],
                "missed_keywords": [k for k in case.expected_keywords if k not in answer],
            },
            trace_id=trace_id,
        )

    def _score_keywords(self, expected: list[str], answer: str) -> float:
        """关键词命中率。"""
        if not expected:
            return 1.0  # 无期望关键词，该项满分
        hit = sum(1 for k in expected if k in answer)
        return hit / len(expected)

    def _score_sources(self, expected: list[str], trace_id: str) -> float:
        """来源正确性：trace_events 里 tool_call 引用的 note_id 是否命中期望。"""
        if not expected:
            return 1.0  # 无期望来源，该项满分

        # 从 trace_events 提取本次问答引用的 note_id
        events = self._ms.get_trace_events(trace_id)
        cited_ids: set[str] = set()
        for e in events:
            if e["event_type"] == "tool":
                # tool 的 input 可能含 note_id（如 get_note_detail）
                inp = e.get("input", "")
                for nid in expected:
                    if nid in inp:
                        cited_ids.add(nid)
                # tool 的 output 也可能含 note_id
                out = e.get("output", "")
                for nid in expected:
                    if nid in out:
                        cited_ids.add(nid)

        if not expected:
            return 1.0
        return len(cited_ids & set(expected)) / len(expected)

    def _score_completeness(self, answer: str) -> float:
        """完整性：非空、长度合理。"""
        if not answer or not answer.strip():
            return 0.0
        if len(answer) < 20:
            return 0.3  # 过短
        if len(answer) < 50:
            return 0.6
        return 1.0


def seed_golden_dataset(metadata_store, yaml_path: str | Path = "tests/eval/golden_dataset.yaml") -> int:
    """从 YAML 种子文件导入 golden cases 到数据库。

    已存在的 id 会被覆盖（更新）。返回导入条数。
    """
    path = Path(yaml_path)
    if not path.exists():
        return 0

    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or []

    count = 0
    for item in data:
        metadata_store.add_golden_case(
            case_id=item["id"],
            question=item["question"],
            expected_keywords=item.get("expected_keywords", []),
            expected_sources=item.get("expected_sources", []),
            min_score=float(item.get("min_score", 0.7)),
        )
        count += 1

    logger.info(f"从 {path.name} 导入 {count} 条 golden cases 到数据库")
    return count
