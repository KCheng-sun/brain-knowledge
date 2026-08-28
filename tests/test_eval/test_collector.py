"""Bad Case 收集器测试（Phase 5D FR54）。

collector 现在写入数据库，不再写 YAML。
"""


from brain.eval.collector import collect_bad_case


class TestCollectBadCase:
    """Bad case 收集测试（写数据库）。"""

    def test_collect_writes_to_db(self, metadata_store):
        """收集的 bad case 写入数据库。"""
        collect_bad_case(
            metadata_store,
            trace_id="trace_123",
            question="测试问题",
            answer="测试回答",
            reason="user_thumbs_down",
        )

        cases = metadata_store.get_bad_cases()
        assert len(cases) == 1
        assert cases[0]["trace_id"] == "trace_123"
        assert cases[0]["question"] == "测试问题"
        assert cases[0]["reason"] == "user_thumbs_down"
        assert "collected_at" in cases[0]

    def test_collect_multiple(self, metadata_store):
        """多次收集都入库。"""
        collect_bad_case(metadata_store, "t1", "Q1", "A1", "user_thumbs_down")
        collect_bad_case(metadata_store, "t2", "Q2", "A2", "empty_answer")

        cases = metadata_store.get_bad_cases()
        assert len(cases) == 2
        # 按时间倒序，后收集的在前
        assert cases[0]["trace_id"] == "t2"
        assert cases[1]["trace_id"] == "t1"

    def test_collect_with_extra_info(self, metadata_store):
        """附加信息被记录。"""
        collect_bad_case(
            metadata_store, "t", "Q", "A", "error",
            extra={"error": "LLM timeout", "model": "deepseek"},
        )

        cases = metadata_store.get_bad_cases()
        assert cases[0]["extra"]["error"] == "LLM timeout"
        assert cases[0]["extra"]["model"] == "deepseek"

    def test_collect_empty_answer(self, metadata_store):
        """空回答可正常收集。"""
        collect_bad_case(metadata_store, "t", "Q", "", "empty_answer")

        cases = metadata_store.get_bad_cases()
        assert cases[0]["answer"] == ""
        assert cases[0]["reason"] == "empty_answer"

    def test_collect_none_trace_id(self, metadata_store):
        """trace_id 为 None 时正常收集。"""
        collect_bad_case(metadata_store, None, "Q", "A", "error")

        cases = metadata_store.get_bad_cases()
        assert cases[0]["trace_id"] == ""

    def test_collect_failure_does_not_raise(self):
        """收集失败不抛异常（不影响主流程）。"""
        # 传入一个未初始化的 store（模拟故障）
        class BrokenStore:
            def add_bad_case(self, **kwargs):
                raise RuntimeError("DB 故障")

        # 不应抛异常
        collect_bad_case(BrokenStore(), "t", "Q", "A", "error")
