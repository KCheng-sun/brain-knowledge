"""离线评估运行器测试（Phase 5D FR53）。

不调真实 LLM，mock ResearcherAgent.research_sync，
验证打分逻辑（关键词命中 + 来源正确性 + 完整性）和报告生成。
"""

import pytest

from brain.eval.runner import EvalRunner


@pytest.fixture
def eval_runner(metadata_store, vector_store):
    """评估运行器（复用 conftest 的 store fixture）。"""
    return EvalRunner(vector_store, metadata_store)


@pytest.fixture
def mock_research(monkeypatch):
    """mock ResearcherAgent.research_sync，返回固定回答。"""
    from brain.agents.researcher import ResearcherAgent

    answers = {}

    def fake_research(self, question, trace_id=None):
        return answers.get(question, "默认回答")

    monkeypatch.setattr(ResearcherAgent, "research_sync", fake_research)
    return answers


class TestScoring:
    """打分逻辑单元测试。"""

    def test_score_keywords_all_hit(self, eval_runner):
        """全部关键词命中得满分。"""
        score = eval_runner._score_keywords(["checkpoint", "持久化"], "checkpoint 机制支持持久化")
        assert score == 1.0

    def test_score_keywords_partial_hit(self, eval_runner):
        """部分命中按比例得分。"""
        score = eval_runner._score_keywords(["a", "b", "c", "d"], "a 和 b 出现了")
        assert score == 0.5

    def test_score_keywords_no_expected(self, eval_runner):
        """无期望关键词得满分。"""
        score = eval_runner._score_keywords([], "任意回答")
        assert score == 1.0

    def test_score_completeness_empty(self, eval_runner):
        """空回答得 0 分。"""
        assert eval_runner._score_completeness("") == 0.0
        assert eval_runner._score_completeness("   ") == 0.0

    def test_score_completeness_short(self, eval_runner):
        """过短回答得低分。"""
        assert eval_runner._score_completeness("短") == 0.3  # <20
        assert eval_runner._score_completeness("二" * 30) == 0.6  # 20-50

    def test_score_completeness_good(self, eval_runner):
        """合理长度得满分（>=50 字符）。"""
        long_answer = "这" * 55  # 确保 >=50
        assert len(long_answer) >= 50
        assert eval_runner._score_completeness(long_answer) == 1.0

    def test_score_sources_no_expected(self, eval_runner):
        """无期望来源得满分。"""
        score = eval_runner._score_sources([], "any_trace")
        assert score == 1.0


class TestEvalRunner:
    """评估运行器集成测试。"""

    def test_load_dataset(self, eval_runner, tmp_path):
        """加载 YAML 测试集。"""
        dataset = tmp_path / "test.yaml"
        dataset.write_text(
            """
- id: t1
  question: "问题1"
  expected_keywords: ["a", "b"]
  expected_sources: ["note1"]
  min_score: 0.7
- id: t2
  question: "问题2"
  expected_keywords: ["c"]
  expected_sources: []
  min_score: 0.6
""",
            encoding="utf-8",
        )

        cases = eval_runner.load_dataset(dataset)
        assert len(cases) == 2
        assert cases[0].id == "t1"
        assert cases[0].expected_keywords == ["a", "b"]
        assert cases[1].min_score == 0.6

    def test_load_dataset_not_found(self, eval_runner):
        """测试集不存在应抛异常。"""
        with pytest.raises(FileNotFoundError):
            eval_runner.load_dataset("nonexistent.yaml")

    def test_run_with_mock_high_score(self, eval_runner, mock_research, tmp_path):
        """高质量回答应通过。"""
        dataset = tmp_path / "ds.yaml"
        dataset.write_text(
            """
- id: t1
  question: "LangGraph 是什么？"
  expected_keywords: ["LangGraph", "Agent", "框架"]
  expected_sources: []
  min_score: 0.7
""",
            encoding="utf-8",
        )
        mock_research["LangGraph 是什么？"] = (
            "LangGraph 是一个用于构建 Agent 的框架，支持状态管理和流程编排。"
            "它通过图结构组织 Agent 的工作流程，是 LangChain 生态的核心组件。"
        )

        report = eval_runner.run(dataset)
        assert report.total == 1
        assert report.passed == 1
        assert report.avg_score >= 0.7

    def test_run_with_mock_low_score(self, eval_runner, mock_research, tmp_path):
        """低质量回答应失败。"""
        dataset = tmp_path / "ds.yaml"
        dataset.write_text(
            """
- id: t1
  question: "详细解释 asyncio"
  expected_keywords: ["asyncio", "事件循环", "epoll", "协程"]
  expected_sources: []
  min_score: 0.7
""",
            encoding="utf-8",
        )
        # 回答只命中一个关键词，且很短
        mock_research["详细解释 asyncio"] = "asyncio 是 Python 的库。"

        report = eval_runner.run(dataset)
        assert report.failed == 1
        assert report.results[0].score < 0.7

    def test_run_handles_exception(self, eval_runner, monkeypatch, tmp_path):
        """问答抛异常时应标记失败而非崩溃。"""
        from brain.agents.researcher import ResearcherAgent

        def raise_research(self, question, trace_id=None):
            raise RuntimeError("LLM 故障")

        monkeypatch.setattr(ResearcherAgent, "research_sync", raise_research)

        dataset = tmp_path / "ds.yaml"
        dataset.write_text(
            """
- id: t1
  question: "任何问题"
  expected_keywords: ["a"]
  expected_sources: []
  min_score: 0.5
""",
            encoding="utf-8",
        )

        report = eval_runner.run(dataset)
        assert report.failed == 1
        assert report.results[0].error is not None
        assert "LLM 故障" in report.results[0].error

    def test_report_summary(self, eval_runner, mock_research, tmp_path):
        """报告摘要格式正确。"""
        dataset = tmp_path / "ds.yaml"
        dataset.write_text(
            """
- id: t1
  question: "Q1"
  expected_keywords: ["a"]
  expected_sources: []
  min_score: 0.5
- id: t2
  question: "Q2"
  expected_keywords: ["x", "y", "z"]
  expected_sources: []
  min_score: 0.9
""",
            encoding="utf-8",
        )
        mock_research["Q1"] = "a 出现了，这是一个足够长的回答超过五十字符用于测试完整性评分逻辑。"
        mock_research["Q2"] = "只有 x"  # 只命中 1/3 关键词

        report = eval_runner.run(dataset)
        summary = report.summary()
        assert "通过率" in summary
        assert str(report.passed) in summary

    def test_source_scoring_with_trace_events(self, eval_runner, metadata_store):
        """来源正确性：trace_events 含期望 note_id 时得分高。"""
        # 手动写入 trace_events，模拟工具调用了期望的 note_id
        metadata_store.add_trace_event(
            "test_trace", "tool_start", name="get_note_detail",
            input_data='{"note_id": "abc123"}',
        )
        metadata_store.add_trace_event(
            "test_trace", "tool_end", output="笔记 abc123 的内容",
        )

        score = eval_runner._score_sources(["abc123"], "test_trace")
        assert score == 1.0

    def test_source_scoring_missing(self, eval_runner, metadata_store):
        """来源正确性：未引用期望 note_id 时得 0 分。"""
        metadata_store.add_trace_event(
            "test_trace2", "tool_start", name="search_notes",
            input_data='{"query": "其他内容"}',
        )
        metadata_store.add_trace_event("test_trace2", "tool_end", output="搜索结果")

        score = eval_runner._score_sources(["abc123"], "test_trace2")
        assert score == 0.0
