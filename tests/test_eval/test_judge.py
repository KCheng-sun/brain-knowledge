"""LLM-as-Judge 评估器测试（Phase 5D FR55）。

不调真实 LLM，mock ChatModel.invoke，验证打分解析和 eval_scores 写入。
"""

from types import SimpleNamespace

from brain.eval.judge import LLMJudge


class TestJudgeParsing:
    """Judge 响应解析测试。"""

    def test_parse_clean_json(self, metadata_store):
        """干净的 JSON 响应直接解析。"""
        judge = LLMJudge(metadata_store)
        result = judge._parse_judge_response(
            '{"score": 4, "dimensions": {"relevance": 5, "accuracy": 4, "completeness": 3}, "comment": "不错"}'
        )
        assert result["score"] == 4
        assert result["dimensions"]["relevance"] == 5
        assert result["comment"] == "不错"

    def test_parse_json_with_extra_text(self, metadata_store):
        """JSON 前后有额外文本时提取 JSON 块。"""
        judge = LLMJudge(metadata_store)
        result = judge._parse_judge_response(
            '以下是评估结果：\n{"score": 3, "dimensions": {"relevance": 3, "accuracy": 3, "completeness": 3}, "comment": "一般"}\n谢谢'
        )
        assert result["score"] == 3

    def test_parse_invalid_returns_default(self, metadata_store):
        """完全无法解析时返回默认值。"""
        judge = LLMJudge(metadata_store)
        result = judge._parse_judge_response("这不是 JSON")
        assert result["score"] == 0
        assert "raw" in result


class TestJudgeExecution:
    """Judge 执行流程测试（mock LLM）。"""

    def _mock_llm(self, response_text: str):
        """构造返回固定文本的 mock LLM。"""
        class MockLLM:
            def invoke(self, messages):
                return SimpleNamespace(content=response_text)
        return MockLLM()

    def test_judge_writes_eval_score(self, metadata_store):
        """打分后写入 eval_scores 表。"""
        llm = self._mock_llm(
            '{"score": 5, "dimensions": {"relevance": 5, "accuracy": 5, "completeness": 5}, "comment": "优秀"}'
        )
        judge = LLMJudge(metadata_store, llm=llm)

        result = judge.judge("什么是 LangGraph？", "LangGraph 是一个图框架", "参考片段", trace_id="t1")

        assert result["score"] == 5
        scores = metadata_store.get_eval_scores(limit=10)
        assert len(scores) == 1
        assert scores[0]["score"] == 5
        assert scores[0]["trace_id"] == "t1"
        assert scores[0]["dimensions"]["accuracy"] == 5

    def test_judge_handles_llm_error(self, metadata_store):
        """LLM 调用失败时返回 score=0，不抛异常。"""
        class BrokenLLM:
            def invoke(self, messages):
                raise RuntimeError("API 故障")

        judge = LLMJudge(metadata_store, llm=BrokenLLM())
        result = judge.judge("Q", "A", trace_id="t2")

        assert result["score"] == 0
        assert "error" in result

    def test_judge_recent_traces_empty(self, metadata_store):
        """无 trace 时返回空列表。"""
        judge = LLMJudge(metadata_store, llm=self._mock_llm('{"score": 5}'))
        results = judge.judge_recent_traces()
        assert results == []


class TestEvalScoresStore:
    """eval_scores 表 CRUD 测试。"""

    def test_add_and_get_eval_score(self, metadata_store):
        """记录的打分能取回。"""
        metadata_store.add_eval_score(
            "t1", "问题1", "回答1", 4,
            dimensions={"relevance": 4, "accuracy": 5, "completeness": 3},
            comment="不错",
        )
        scores = metadata_store.get_eval_scores(limit=10)
        assert len(scores) == 1
        assert scores[0]["score"] == 4
        assert scores[0]["dimensions"]["accuracy"] == 5
        assert scores[0]["comment"] == "不错"

    def test_eval_score_summary(self, metadata_store):
        """汇总统计正确。"""
        metadata_store.add_eval_score("t1", "Q1", "A1", 5, comment="优")
        metadata_store.add_eval_score("t2", "Q2", "A2", 4, comment="好")
        metadata_store.add_eval_score("t3", "Q3", "A3", 3, comment="一般")
        metadata_store.add_eval_score("t4", "Q4", "A4", 2, comment="差")

        summary = metadata_store.get_eval_score_summary()
        assert summary["total"] == 4
        assert summary["avg_score"] == 3.5  # (5+4+3+2)/4
        assert summary["distribution"]["good"] == 2  # 4-5 分
        assert summary["distribution"]["mid"] == 1   # 3 分
        assert summary["distribution"]["bad"] == 1   # 1-2 分

    def test_eval_score_summary_empty(self, metadata_store):
        """空表汇总返回零值。"""
        summary = metadata_store.get_eval_score_summary()
        assert summary["total"] == 0
        assert summary["avg_score"] == 0

    def test_eval_scores_ordered_desc(self, metadata_store):
        """打分按时间倒序。"""
        metadata_store.add_eval_score("t1", "Q1", "A1", 3)
        metadata_store.add_eval_score("t2", "Q2", "A2", 4)

        scores = metadata_store.get_eval_scores(limit=10)
        assert scores[0]["trace_id"] == "t2"  # 后记录的在前
        assert scores[1]["trace_id"] == "t1"
