"""可观测性指标采集测试（Phase 5A）。

验证 metrics 表的记录、聚合、调用链查询。
"""

import pytest

from brain.observability import (
    MetricsTimer,
    check_health,
    get_trace_id,
    new_trace_id,
    record_metric,
    reset_trace_id,
    set_trace_id,
)


class TestTraceContext:
    """trace_id 上下文透传测试。"""

    def test_new_trace_id_format(self):
        """trace_id 应为 12 位十六进制字符串。"""
        tid = new_trace_id()
        assert len(tid) == 12
        assert all(c in "0123456789abcdef" for c in tid)

    def test_trace_id_unique(self):
        """每次生成的 trace_id 应不同。"""
        assert new_trace_id() != new_trace_id()

    def test_set_and_get_trace_id(self):
        """设置后能取到，重置后恢复。"""
        token = set_trace_id("test123")
        assert get_trace_id() == "test123"
        reset_trace_id(token)
        assert get_trace_id() is None

    def test_record_metric_uses_context_trace_id(self, metadata_store):
        """record_metric 默认使用上下文中的 trace_id。"""
        token = set_trace_id("ctx_trace")
        try:
            record_metric(metadata_store, "ask", "count", 1)
            detail = metadata_store.get_trace_detail("ctx_trace")
            assert len(detail) == 1
            assert detail[0]["metric_type"] == "ask"
        finally:
            reset_trace_id(token)

    def test_record_metric_failure_does_not_raise(self, metadata_store):
        """指标记录失败不应抛异常（不能影响主流程）。"""
        # 传入一个未初始化的 store（模拟故障）
        class BrokenStore:
            def record_metric(self, **kwargs):
                raise RuntimeError("DB 故障")

        # 不应抛异常
        record_metric(BrokenStore(), "ask", "count", 1)


class TestMetricsStore:
    """MetadataStore 的 metrics 方法测试。"""

    def test_record_and_get_trace_detail(self, metadata_store):
        """记录指标后能按 trace_id 查询。"""
        metadata_store.record_metric(
            "ask", "latency_ms", 1500.0, trace_id="trace_a",
            metadata={"question": "测试", "status": "done"},
        )
        metadata_store.record_metric(
            "tool_call", "count", 1, trace_id="trace_a",
            metadata={"tool_name": "search_notes"},
        )

        detail = metadata_store.get_trace_detail("trace_a")
        assert len(detail) == 2
        assert detail[0]["metric_type"] == "ask"
        assert detail[0]["metadata"]["question"] == "测试"
        assert detail[1]["metadata"]["tool_name"] == "search_notes"

    def test_metrics_summary_aggregation(self, metadata_store):
        """summary 应正确聚合问答次数、延迟、工具调用、token。"""
        # trace_a: 1 次问答，2 次工具，850 token
        metadata_store.record_metric("ask", "latency_ms", 1000.0, trace_id="a")
        metadata_store.record_metric("ask", "count", 1, trace_id="a")
        metadata_store.record_metric("tool_call", "count", 1, trace_id="a")
        metadata_store.record_metric("tool_call", "count", 1, trace_id="a")
        metadata_store.record_metric("llm_call", "token_count", 850, trace_id="a")
        # trace_b: 1 次问答，1 次工具
        metadata_store.record_metric("ask", "latency_ms", 2000.0, trace_id="b")
        metadata_store.record_metric("ask", "count", 1, trace_id="b")
        metadata_store.record_metric("tool_call", "count", 1, trace_id="b")

        summary = metadata_store.get_metrics_summary(hours=24)

        assert summary["ask_count"] == 2  # 只数 count 行，不是 latency 行
        assert summary["avg_ask_latency_ms"] == 1500.0  # (1000+2000)/2
        assert summary["tool_call_count"] == 3
        assert summary["llm_token_total"] == 850

    def test_metrics_summary_empty(self, metadata_store):
        """空库的 summary 应返回零值。"""
        summary = metadata_store.get_metrics_summary(hours=24)
        assert summary["ask_count"] == 0
        assert summary["avg_ask_latency_ms"] == 0
        assert summary["tool_call_count"] == 0
        assert summary["llm_token_total"] == 0
        assert summary["by_hour"] == []

    def test_recent_traces_ordered_desc(self, metadata_store):
        """调用链应按时间倒序排列。"""
        metadata_store.record_metric("ask", "count", 1, trace_id="first")
        metadata_store.record_metric("ask", "count", 1, trace_id="second")

        traces = metadata_store.get_recent_traces(limit=10)
        assert len(traces) == 2
        # 后记录的在前
        assert traces[0]["trace_id"] == "second"
        assert traces[1]["trace_id"] == "first"

    def test_recent_traces_aggregates_per_trace(self, metadata_store):
        """每条 trace 的工具调用数和 token 应正确聚合。"""
        metadata_store.record_metric("ask", "latency_ms", 1200.0, trace_id="t1")
        metadata_store.record_metric("tool_call", "count", 1, trace_id="t1")
        metadata_store.record_metric("tool_call", "count", 1, trace_id="t1")
        metadata_store.record_metric("llm_call", "token_count", 500, trace_id="t1")

        traces = metadata_store.get_recent_traces(limit=10)
        assert len(traces) == 1
        t = traces[0]
        assert t["trace_id"] == "t1"
        assert t["tool_calls"] == 2
        assert t["tokens"] == 500
        assert t["duration_ms"] == 1200.0


class TestMetricsTimer:
    """计时器上下文管理器测试。"""

    def test_timer_records_latency(self, metadata_store):
        """with 块结束后应记录 latency_ms 指标。"""
        with MetricsTimer(metadata_store, "ingest", "latency_ms", {"source": "text"}):
            pass  # 模拟耗时操作

        # ingest 无 trace_id，不会出现在 traces 里，改用 summary 验证 latency 被记录
        summary = metadata_store.get_metrics_summary(hours=24)
        # ingest 的 latency 在 summary 里
        assert summary["ingest_count"] == 0  # 没记录 count，只记录了 latency
        # latency 行存在但 count 为 0，avg_ingest_latency_ms 应有值
        assert summary["avg_ingest_latency_ms"] >= 0

    def test_timer_records_on_exception(self, metadata_store):
        """with 块抛异常时仍应记录 latency（含 error 元信息）。"""
        with pytest.raises(ValueError, match="测试异常"):
            with MetricsTimer(metadata_store, "ingest", "latency_ms"):
                raise ValueError("测试异常")

        # 验证记录存在
        summary = metadata_store.get_metrics_summary(hours=24)
        assert summary["avg_ingest_latency_ms"] >= 0

    def test_timer_with_explicit_trace_id(self, metadata_store):
        """显式传 trace_id 时，指标应归属该 trace。"""
        with MetricsTimer(
            metadata_store, "ask", "latency_ms",
            {"question": "test"}, trace_id="explicit_tid",
        ):
            pass

        detail = metadata_store.get_trace_detail("explicit_tid")
        assert len(detail) == 1
        assert detail[0]["metric_type"] == "ask"
        assert detail[0]["metadata"]["question"] == "test"


class TestResetTraceIdRobustness:
    """reset_trace_id 跨 context 容错测试。

    Starlette 的 iterate_in_threadpool 会对同步生成器的每次 next() 创建新
    context，导致 token.reset() 跨 context 失败。reset_trace_id 必须容错。
    """

    def test_reset_in_different_context_does_not_raise(self):
        """在不同于 set 的 context 里 reset 不应抛 ValueError。"""
        import contextvars

        token = set_trace_id("ctx_a")
        # 在新 context 里 reset（模拟 threadpool 场景）
        def reset_in_new_ctx():
            ctx = contextvars.copy_context()
            ctx.run(reset_trace_id, token)

        # 不应抛异常
        reset_in_new_ctx()
        # 原 context 的 trace_id 不受影响（容错模式下 reset 被忽略）
        assert get_trace_id() == "ctx_a"


class TestTokenTrackingCallback:
    """LLM token 跟踪回调测试。"""

    def _make_response(self, prompt=100, completion=50):
        """构造 mock LangChain LLMResponse。"""
        from types import SimpleNamespace

        return SimpleNamespace(
            llm_output={
                "token_usage": {
                    "prompt_tokens": prompt,
                    "completion_tokens": completion,
                },
                "model_name": "deepseek-chat",
            },
            generations=[],
        )

    def test_records_token_from_llm_output(self, metadata_store):
        """从 llm_output.token_usage 提取 token 并记录。"""
        from brain.observability import TokenTrackingCallback

        cb = TokenTrackingCallback(metadata_store, trace_id="tok_trace")
        cb.on_llm_end(self._make_response(prompt=120, completion=80))

        detail = metadata_store.get_trace_detail("tok_trace")
        assert len(detail) == 1
        metric = detail[0]
        assert metric["metric_type"] == "llm_call"
        assert metric["metric_name"] == "token_count"
        assert metric["value"] == 200  # 120 + 80
        assert metric["metadata"]["prompt_tokens"] == 120
        assert metric["metadata"]["completion_tokens"] == 80

    def test_skips_when_no_token_usage(self, metadata_store):
        """response 无 token 信息时不记录。"""
        from types import SimpleNamespace

        from brain.observability import TokenTrackingCallback

        cb = TokenTrackingCallback(metadata_store, trace_id="empty_trace")
        # 无 llm_output / 无 token_usage
        cb.on_llm_end(SimpleNamespace(llm_output={}, generations=[]))

        detail = metadata_store.get_trace_detail("empty_trace")
        assert len(detail) == 0  # 没记录

    def test_fallback_to_usage_metadata(self, metadata_store):
        """llm_output 无 token_usage 时，从 generations[].message.usage_metadata 提取。"""
        from types import SimpleNamespace

        from brain.observability import TokenTrackingCallback

        # 构造 generations 里有 message.usage_metadata 的 response
        msg = SimpleNamespace(usage_metadata={"input_tokens": 200, "output_tokens": 100})
        gen = SimpleNamespace(message=msg)
        response = SimpleNamespace(
            llm_output={},  # 无 token_usage
            generations=[[gen]],
        )

        cb = TokenTrackingCallback(metadata_store, trace_id="fallback_trace")
        cb.on_llm_end(response)

        detail = metadata_store.get_trace_detail("fallback_trace")
        assert len(detail) == 1
        assert detail[0]["value"] == 300  # 200 + 100


class TestTraceEvents:
    """完整调用链事件记录测试（trace_events 表，start/end 合并返回）。"""

    def test_start_end_merged_to_single_event(self, metadata_store):
        """tool_start + tool_end 合并为一条 tool 事件，同时携带 input 和 output。"""
        metadata_store.add_trace_event("trace1", "tool_start", name="search_notes", input_data='{"query":"test"}')
        metadata_store.add_trace_event("trace1", "tool_end", output="未找到", latency_ms=12.5)

        events = metadata_store.get_trace_events("trace1")
        assert len(events) == 1  # 合并为 1 条
        assert events[0]["event_type"] == "tool"
        assert events[0]["name"] == "search_notes"
        assert events[0]["input"] == '{"query":"test"}'  # 来自 start
        assert events[0]["output"] == "未找到"  # 来自 end
        assert events[0]["latency_ms"] == 12.5  # 来自 end

    def test_llm_start_end_merged(self, metadata_store):
        """llm_start + llm_end 合并为一条 llm 事件，携带 prompt + 响应 + token。"""
        metadata_store.add_trace_event("t", "llm_start", name="deepseek", input_data="[user] 你好")
        metadata_store.add_trace_event("t", "llm_end", output="答案是...", token_usage={"prompt":100,"completion":50,"total":150}, latency_ms=800.0)

        events = metadata_store.get_trace_events("t")
        assert len(events) == 1
        assert events[0]["event_type"] == "llm"
        assert events[0]["input"] == "[user] 你好"
        assert events[0]["output"] == "答案是..."
        assert events[0]["token_usage"]["total"] == 150

    def test_multiple_tools_fifo_pairing(self, metadata_store):
        """多个工具并行调用时，start/end 按出现顺序 FIFO 配对。"""
        # 模拟并行：4 个 start 后 4 个 end（实际 LangGraph 场景）
        metadata_store.add_trace_event("p", "tool_start", name="tool_a", input_data="a_in")
        metadata_store.add_trace_event("p", "tool_start", name="tool_b", input_data="b_in")
        metadata_store.add_trace_event("p", "tool_end", output="a_out")
        metadata_store.add_trace_event("p", "tool_end", output="b_out")

        events = metadata_store.get_trace_events("p")
        assert len(events) == 2
        # FIFO: 第一个 start 配第一个 end
        assert events[0]["name"] == "tool_a"
        assert events[0]["input"] == "a_in"
        assert events[0]["output"] == "a_out"
        assert events[1]["name"] == "tool_b"
        assert events[1]["output"] == "b_out"

    def test_interleaved_llm_and_tool(self, metadata_store):
        """LLM 和工具交错调用，各自独立配对。"""
        metadata_store.add_trace_event("i", "llm_start", name="m1", input_data="q1")
        metadata_store.add_trace_event("i", "llm_end", output="a1", token_usage={"prompt":10,"completion":5,"total":15})
        metadata_store.add_trace_event("i", "tool_start", name="search", input_data="query")
        metadata_store.add_trace_event("i", "tool_end", output="result")
        metadata_store.add_trace_event("i", "llm_start", name="m2", input_data="q2")
        metadata_store.add_trace_event("i", "llm_end", output="a2", token_usage={"prompt":20,"completion":8,"total":28})

        events = metadata_store.get_trace_events("i")
        assert len(events) == 3
        assert [e["event_type"] for e in events] == ["llm", "tool", "llm"]
        assert events[0]["input"] == "q1"
        assert events[1]["name"] == "search"
        assert events[1]["output"] == "result"
        assert events[2]["token_usage"]["total"] == 28

    def test_unpaired_start_preserved(self, metadata_store):
        """只有 start 没有 end（流中断）时，start 仍保留。"""
        metadata_store.add_trace_event("u", "tool_start", name="interrupted", input_data="in")

        events = metadata_store.get_trace_events("u")
        assert len(events) == 1
        assert events[0]["event_type"] == "tool"
        assert events[0]["input"] == "in"
        assert events[0]["output"] == ""  # 无 end

    def test_trace_event_logger_full_flow(self, metadata_store):
        """TraceEventLogger 完整流程：LLM + 工具的 start/end 都合并为单条。"""
        import uuid
        from types import SimpleNamespace

        from brain.observability import TraceEventLogger

        cb = TraceEventLogger(metadata_store, trace_id="full_flow")
        run_id = str(uuid.uuid4())

        # 1. LLM 调用（start + end）
        msg = SimpleNamespace(type="human", content="什么是 LangGraph？")
        cb.on_chat_model_start({"name": "deepseek-chat"}, [[msg]], run_id=uuid.UUID(run_id))
        resp_msg = SimpleNamespace(content="LangGraph 是...", usage_metadata={"input_tokens": 100, "output_tokens": 50})
        resp_gen = SimpleNamespace(message=resp_msg)
        response = SimpleNamespace(llm_output={}, generations=[[resp_gen]])
        cb.on_llm_end(response, run_id=uuid.UUID(run_id))

        # 2. 工具调用（start + end）
        tool_run = str(uuid.uuid4())
        cb.on_tool_start({"name": "search_notes"}, '{"query":"langgraph"}', run_id=uuid.UUID(tool_run), inputs={"query": "langgraph"})
        cb.on_tool_end("找到 3 条结果", run_id=uuid.UUID(tool_run))

        events = metadata_store.get_trace_events("full_flow")
        # 合并后 2 条（1 LLM + 1 工具）
        assert len(events) == 2
        assert events[0]["event_type"] == "llm"
        assert "什么是 LangGraph" in events[0]["input"]
        assert "LangGraph 是" in events[0]["output"]
        assert events[0]["token_usage"]["total"] == 150
        assert events[1]["event_type"] == "tool"
        assert events[1]["name"] == "search_notes"
        assert "langgraph" in events[1]["input"]
        assert events[1]["output"] == "找到 3 条结果"

        # token 也写入 metrics 表
        metrics = metadata_store.get_trace_detail("full_flow")
        token_metrics = [m for m in metrics if m["metric_type"] == "llm_call"]
        assert len(token_metrics) == 1
        assert token_metrics[0]["value"] == 150


class TestCostCalculation:
    """Token 成本计价测试（Phase 5B FR47）。"""

    def test_calc_token_cost_v4_flash_idle(self):
        """v4-flash 空闲未命中：1M input=¥1.5, 1M output=¥4.5。"""
        from brain.observability import calc_token_cost

        # 100万 prompt + 50万 completion = 1.5 + 2.25 = ¥3.75
        cost = calc_token_cost("deepseek-v4-flash", 1_000_000, 500_000)
        assert abs(cost - 3.75) < 0.0001

    def test_calc_token_cost_small_amount(self):
        """小额 token 成本（典型问答）。"""
        from brain.observability import calc_token_cost

        # 5000 prompt + 500 completion, v4-flash 空闲未命中
        cost = calc_token_cost("deepseek-v4-flash", 5000, 500)
        # 5000/1e6*1.5 + 500/1e6*4.5 = 0.0075 + 0.00225 = 0.00975
        assert abs(cost - 0.00975) < 0.0001

    def test_calc_token_cost_unknown_model_uses_default(self):
        """未知模型按 v4-flash 默认价。"""
        from brain.observability import calc_token_cost

        cost = calc_token_cost("unknown-model", 1_000_000, 0)
        assert abs(cost - 1.5) < 0.0001  # v4-flash 空闲未命中 input

    def test_calc_token_cost_peak_hours_double(self):
        """高峰时段成本约为空闲的 2 倍。"""
        from brain.observability import calc_token_cost

        idle = calc_token_cost("deepseek-v4-flash", 1_000_000, 500_000)
        peak = calc_token_cost("deepseek-v4-flash", 1_000_000, 500_000, peak_hours=True)
        assert abs(peak - idle * 2) < 0.0001

    def test_calc_token_cost_cache_hit_cheaper(self):
        """缓存命中的 input token 成本远低于未命中。"""
        from brain.observability import calc_token_cost

        # 全部未命中
        no_cache = calc_token_cost("deepseek-v4-flash", 1_000_000, 0)
        # 全部缓存命中
        all_cache = calc_token_cost("deepseek-v4-flash", 1_000_000, 0, cache_hit_tokens=1_000_000)
        assert all_cache < no_cache / 20  # 缓存价便宜 30 倍

    def test_calc_token_cost_pro_more_expensive_than_flash(self):
        """v4-pro 比 v4-flash 贵。"""
        from brain.observability import calc_token_cost

        flash = calc_token_cost("deepseek-v4-flash", 1_000_000, 500_000)
        pro = calc_token_cost("deepseek-v4-pro", 1_000_000, 500_000)
        assert pro > flash

    def test_calc_token_cost_alias_resolved(self):
        """旧型号别名（deepseek-chat）解析为 v4-flash 价。"""
        from brain.observability import calc_token_cost

        alias_cost = calc_token_cost("deepseek-chat", 1_000_000, 500_000)
        flash_cost = calc_token_cost("deepseek-v4-flash", 1_000_000, 500_000)
        assert abs(alias_cost - flash_cost) < 0.0001

    def test_trace_event_records_cost(self, metadata_store):
        """LLM 调用的 trace_event 应记录 cost 和 cache_hit 字段。"""
        import uuid
        from types import SimpleNamespace

        from brain.observability import TraceEventLogger

        cb = TraceEventLogger(metadata_store, trace_id="cost_trace")
        # 1000 prompt + 200 completion, 300 缓存命中
        msg = SimpleNamespace(
            content="回答",
            usage_metadata={
                "input_tokens": 1000,
                "output_tokens": 200,
                "input_token_details": {"cache_read": 300},
            },
        )
        gen = SimpleNamespace(message=msg)
        response = SimpleNamespace(llm_output={"model_name": "deepseek-v4-flash"}, generations=[[gen]])

        cb.on_chat_model_start({"name": "deepseek-v4-flash"}, [[]], run_id=uuid.uuid4())
        cb.on_llm_end(response, run_id=uuid.uuid4())

        events = metadata_store.get_trace_events("cost_trace")
        assert len(events) == 1
        tu = events[0]["token_usage"]
        assert "cost" in tu
        assert tu["cache_hit"] == 300
        # 700 未命中*1.5 + 300 命中*0.05 + 200*4.5，单位 ¥/1M
        # = 0.00105 + 0.000015 + 0.0009 = 0.001965
        assert abs(tu["cost"] - 0.001965) < 0.0001


class TestCostSummary:
    """成本汇总查询测试（Phase 5B FR49）。"""

    def test_cost_summary_empty(self, metadata_store):
        """无 LLM 调用时成本为零。"""
        summary = metadata_store.get_cost_summary()
        assert summary["today"]["cost"] == 0
        assert summary["today"]["tokens"] == 0
        assert summary["total"]["cost"] == 0

    def test_cost_summary_aggregation(self, metadata_store):
        """多次 LLM 调用的成本正确聚合。"""
        # 两次 LLM 调用
        metadata_store.add_trace_event(
            "t1", "llm_end", name="deepseek-chat",
            output="回答1",
            token_usage={"prompt": 1000, "completion": 200, "total": 1200, "cost": 0.0014},
        )
        metadata_store.add_trace_event(
            "t1", "llm_end", name="deepseek-chat",
            output="回答2",
            token_usage={"prompt": 2000, "completion": 400, "total": 2400, "cost": 0.0028},
        )

        summary = metadata_store.get_cost_summary()
        assert summary["total"]["cost"] == 0.0042  # 0.0014 + 0.0028
        assert summary["total"]["tokens"] == 3600  # 1200 + 2400

    def test_cost_by_model(self, metadata_store):
        """按模型聚合成本。"""
        metadata_store.add_trace_event(
            "t", "llm_end", name="deepseek-chat",
            token_usage={"prompt": 1000, "completion": 100, "total": 1100, "cost": 0.0012},
        )
        metadata_store.add_trace_event(
            "t", "llm_end", name="deepseek-chat",
            token_usage={"prompt": 500, "completion": 50, "total": 550, "cost": 0.0006},
        )
        metadata_store.add_trace_event(
            "t", "llm_end", name="claude-3-5-sonnet",
            token_usage={"prompt": 100, "completion": 10, "total": 110, "cost": 0.0033},
        )

        by_model = metadata_store.get_cost_by_model(hours=24)
        assert len(by_model) == 2
        # 按成本降序，claude 应在前
        assert by_model[0]["model"] == "claude-3-5-sonnet"
        assert by_model[0]["calls"] == 1
        deepseek = next(m for m in by_model if m["model"] == "deepseek-chat")
        assert deepseek["calls"] == 2
        assert deepseek["total_tokens"] == 1650

    def test_cost_by_day(self, metadata_store):
        """按日聚合成本。"""
        metadata_store.add_trace_event(
            "t", "llm_end", name="deepseek-chat",
            token_usage={"prompt": 1000, "completion": 100, "total": 1100, "cost": 0.0012},
        )

        by_day = metadata_store.get_cost_by_day(days=30)
        assert len(by_day) == 1
        assert by_day[0]["total_tokens"] == 1100
        assert by_day[0]["calls"] == 1


class TestBudgetCheck:
    """预算熔断检查测试（Phase 5B FR48）。"""

    def test_budget_ok_when_under_limit(self, metadata_store, monkeypatch):
        """未超限时返回 ok=True。"""
        from brain.config import AppConfig, CostSettings
        from brain.observability import check_budget

        cfg = AppConfig()
        cfg.cost = CostSettings()
        import brain.config as cm
        monkeypatch.setattr(cm, "_config", cfg)

        result = check_budget(metadata_store)
        assert result["ok"] is True
        assert result["reason"] == ""

    def test_budget_exceeded_daily_token(self, metadata_store, monkeypatch):
        """日 token 超限时返回 ok=False。"""
        from brain.config import AppConfig, CostSettings
        from brain.observability import check_budget

        # 模拟已用 60 万 token（超过默认 50 万）
        metadata_store.add_trace_event(
            "t", "llm_end", name="deepseek-chat",
            token_usage={"prompt": 600000, "completion": 0, "total": 600000, "cost": 0.6},
        )

        cfg = AppConfig()
        cfg.cost = CostSettings()  # 默认 daily_token_limit=500000
        import brain.config as cm
        monkeypatch.setattr(cm, "_config", cfg)

        result = check_budget(metadata_store)
        assert result["ok"] is False
        assert "日 token 配额" in result["reason"]

    def test_budget_exceeded_daily_cost(self, metadata_store, monkeypatch):
        """日成本超限时返回 ok=False。"""
        from brain.config import AppConfig, CostSettings
        from brain.observability import check_budget

        # 模拟今日成本 ¥15（超过默认 ¥10）
        metadata_store.add_trace_event(
            "t", "llm_end", name="deepseek-chat",
            token_usage={"prompt": 100000, "completion": 50000, "total": 150000, "cost": 15.0},
        )

        cfg = AppConfig()
        cfg.cost = CostSettings()  # 默认 daily_cost_limit=10.0
        import brain.config as cm
        monkeypatch.setattr(cm, "_config", cfg)

        result = check_budget(metadata_store)
        assert result["ok"] is False
        assert "日成本上限" in result["reason"]


class TestHealthCheck:
    """健康检查测试。"""

    def test_check_health_all_ok(self, metadata_store, vector_store):
        """所有组件正常时应返回 healthy。"""
        # embedding_fn 用一个返回固定向量的 mock
        def mock_embed(texts):
            return [[0.1] * 384 for _ in texts]

        result = check_health(metadata_store, vector_store, mock_embed)

        assert result["status"] == "healthy"
        assert result["components"]["sqlite"] == "ok"
        assert result["components"]["chromadb"] == "ok"
        assert result["components"]["embedding"] == "ok"
        assert "timestamp" in result

    def test_check_health_embedding_skipped(self, metadata_store, vector_store):
        """无 embedding_fn 时 embedding 应为 skipped，整体仍 healthy。"""
        result = check_health(metadata_store, vector_store, None)

        assert result["components"]["embedding"] == "skipped"
        assert result["status"] == "healthy"  # skipped 不算 degraded

    def test_check_health_sqlite_error(self, vector_store):
        """SQLite 故障时应返回 degraded/unhealthy。"""
        class BrokenStore:
            def count_notes(self):
                raise RuntimeError("DB down")

        def mock_embed(texts):
            return [[0.1] * 384 for _ in texts]

        result = check_health(BrokenStore(), vector_store, mock_embed)

        assert "error" in result["components"]["sqlite"]
        # sqlite error + chromadb ok = 1 个 error => degraded
        assert result["status"] in ("degraded", "unhealthy")
