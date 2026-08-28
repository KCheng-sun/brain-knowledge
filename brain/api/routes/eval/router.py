"""评估闭环业务域 API 路由。

端点:
  POST   /api/eval/feedback                       — 用户点踩收集 bad case
  GET    /api/eval/scores                         — Judge 打分列表
  GET    /api/eval/scores/summary                 — 打分汇总
  GET    /api/eval/bad-cases                      — bad case 列表
  DELETE /api/eval/bad-cases/{case_id}            — 删除 bad case
  POST   /api/eval/bad-cases/{case_id}/to-golden  — bad case 转 golden
  GET    /api/eval/golden-cases                   — golden case 列表
  POST   /api/eval/golden-cases                   — 新增/更新 golden case
  PATCH  /api/eval/golden-cases/{case_id}         — 更新 golden case
  DELETE /api/eval/golden-cases/{case_id}         — 删除 golden case
  POST   /api/eval/golden-cases/{case_id}/toggle  — 启用/禁用
  POST   /api/eval/seed                           — YAML 种子导入
  GET    /api/eval/runs                           — 评估批次历史
  POST   /api/eval/judge                          — 手动触发 Judge 抽样
  POST   /api/eval/run                            — 手动触发离线评估
"""

from fastapi import APIRouter, HTTPException, Query

from brain.api.deps import get_metadata_store, get_vector_store
from brain.api.routes.eval.models import EvalFeedbackRequest, GoldenCaseRequest

router = APIRouter(prefix="/api/eval", tags=["eval"])


@router.post("/feedback")
def submit_eval_feedback(req: EvalFeedbackRequest):
    """用户点踩 bad case → 收集到数据库。"""
    from brain.eval.collector import collect_bad_case

    collect_bad_case(
        get_metadata_store(),
        trace_id=req.trace_id,
        question=req.question,
        answer=req.answer,
        reason=req.reason,
    )
    return {"message": "已收集，感谢反馈"}


@router.get("/scores")
def get_eval_scores(limit: int = Query(50, ge=1, le=200)):
    """获取最近的 LLM-as-Judge 打分。"""
    return get_metadata_store().get_eval_scores(limit=limit)


@router.get("/scores/summary")
def get_eval_score_summary():
    """评估打分汇总（平均分/分布）。"""
    return get_metadata_store().get_eval_score_summary()


@router.get("/bad-cases")
def get_bad_cases():
    """查看已收集的 bad cases。"""
    return get_metadata_store().get_bad_cases()


@router.delete("/bad-cases/{case_id}")
def delete_bad_case(case_id: int):
    """删除一条 bad case。"""
    ms = get_metadata_store()
    if ms.delete_bad_case(case_id):
        return {"message": "已删除"}
    raise HTTPException(status_code=404, detail="bad case 不存在")


@router.post("/bad-cases/{case_id}/to-golden")
def bad_case_to_golden(case_id: int, min_score: float = Query(0.7, ge=0, le=1.0)):
    """将 bad case 转为 golden case（需人工补充关键词后可启用）。"""
    ms = get_metadata_store()
    cases = ms.get_bad_cases(limit=1000)
    target = next((c for c in cases if c["id"] == case_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="bad case 不存在")

    # 生成 case_id：bc_<id>
    new_id = f"bc_{case_id}"
    ms.add_golden_case(
        case_id=new_id,
        question=target["question"],
        expected_keywords=[],  # 待人工补充
        expected_sources=[],
        min_score=min_score,
        enabled=False,  # 默认禁用，补充关键词后手动启用
    )
    return {"message": f"已转为 golden case（id={new_id}），请补充关键词后启用", "golden_id": new_id}


# ---- Golden Cases CRUD（Phase 5D FR53） ----

@router.get("/golden-cases")
def get_golden_cases(enabled_only: bool = Query(False)):
    """获取 golden cases 列表。"""
    return get_metadata_store().get_golden_cases(enabled_only=enabled_only)


@router.post("/golden-cases")
def create_golden_case(req: GoldenCaseRequest):
    """新增/更新 golden case（id 相同则覆盖）。"""
    ms = get_metadata_store()
    ms.add_golden_case(
        case_id=req.id,
        question=req.question,
        expected_keywords=req.expected_keywords,
        expected_sources=req.expected_sources,
        min_score=req.min_score,
        enabled=req.enabled,
    )
    return {"message": "已保存", "id": req.id}


@router.patch("/golden-cases/{case_id}")
def update_golden_case(case_id: str, req: GoldenCaseRequest):
    """更新 golden case。"""
    ms = get_metadata_store()
    ms.update_golden_case(
        case_id,
        question=req.question,
        expected_keywords=req.expected_keywords,
        expected_sources=req.expected_sources,
        min_score=req.min_score,
        enabled=req.enabled,
    )
    return {"message": "已更新"}


@router.delete("/golden-cases/{case_id}")
def delete_golden_case(case_id: str):
    """删除 golden case。"""
    ms = get_metadata_store()
    if ms.delete_golden_case(case_id):
        return {"message": "已删除"}
    raise HTTPException(status_code=404, detail="golden case 不存在")


@router.post("/golden-cases/{case_id}/toggle")
def toggle_golden_case(case_id: str):
    """启用/禁用 golden case。"""
    ms = get_metadata_store()
    cases = ms.get_golden_cases()
    target = next((c for c in cases if c["id"] == case_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="golden case 不存在")
    ms.update_golden_case(case_id, enabled=not target["enabled"])
    return {"message": "已切换", "enabled": not target["enabled"]}


@router.post("/seed")
def seed_golden_cases():
    """从 YAML 种子文件导入 golden cases 到数据库。"""
    from brain.eval.runner import seed_golden_dataset

    count = seed_golden_dataset(get_metadata_store())
    return {"message": f"已导入 {count} 条", "count": count}


@router.get("/runs")
def get_eval_runs(
    limit: int = Query(20, ge=1, le=100),
    run_type: str | None = Query(None, description="offline | judge，空=全部"),
):
    """获取评估批次历史（Phase 5D）。"""
    return get_metadata_store().get_eval_runs(limit=limit, run_type=run_type)


@router.post("/judge")
def run_judge_sample(sample_rate: float = Query(0.1, ge=0.01, le=1.0), limit: int = Query(10, ge=1, le=50)):
    """手动触发 LLM-as-Judge 抽样打分（Phase 5D FR55）。"""
    from brain.eval.judge import LLMJudge

    judge = LLMJudge(get_metadata_store())
    results = judge.judge_recent_traces(sample_rate=sample_rate, limit=limit)
    return {"judged": len(results), "results": results}


@router.post("/run")
def run_eval_dataset(limit: int = Query(0, ge=0, le=50, description="只跑前 N 条，0=全部")):
    """手动触发离线评估测试集（Phase 5D FR53）。

    跑 Golden Dataset，返回打分报告。注意：会真实调用 LLM，消耗 token。
    """
    from brain.eval.runner import EvalRunner

    ms = get_metadata_store()
    runner = EvalRunner(get_vector_store(), ms)
    actual_limit = limit if limit > 0 else None
    report = runner.run(limit=actual_limit)  # None=从数据库加载

    # 持久化评估批次到 eval_runs（Phase 5D）——存完整结果供历史查看
    all_results = [
        {
            "id": r.case.id,
            "question": r.case.question[:60],
            "answer": r.answer[:200],
            "score": r.score,
            "passed": r.passed,
            "min_score": r.case.min_score,
            "details": r.details,
            "trace_id": r.trace_id,
            "error": r.error,
        }
        for r in report.results
    ]
    ms.add_eval_run(
        run_type="offline",
        total=report.total,
        passed=report.passed,
        pass_rate=round(report.pass_rate, 4),
        avg_score=round(report.avg_score, 4),
        duration_ms=round(report.duration_ms, 0),
        details={"results": all_results},
    )

    # 序列化报告（dataclass → dict）
    return {
        "total": report.total,
        "passed": report.passed,
        "failed": report.failed,
        "pass_rate": round(report.pass_rate, 4),
        "avg_score": round(report.avg_score, 4),
        "duration_ms": round(report.duration_ms, 0),
        "started_at": report.started_at,
        "results": [
            {
                "id": r.case.id,
                "question": r.case.question,
                "answer": r.answer,
                "score": r.score,
                "passed": r.passed,
                "min_score": r.case.min_score,
                "details": r.details,
                "trace_id": r.trace_id,
                "error": r.error,
            }
            for r in report.results
        ],
    }
