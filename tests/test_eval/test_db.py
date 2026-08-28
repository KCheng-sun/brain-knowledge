"""Golden Cases 数据库 CRUD 测试（Phase 5D FR53）。"""


from brain.eval.runner import seed_golden_dataset


class TestGoldenCasesCRUD:
    """golden_cases 表 CRUD 测试。"""

    def test_add_and_get(self, metadata_store):
        """新增并查询 golden case。"""
        metadata_store.add_golden_case(
            "eval_001", "什么是 LangGraph？",
            expected_keywords=["LangGraph", "Agent"],
            expected_sources=["note1", "note2"],
            min_score=0.8,
        )

        cases = metadata_store.get_golden_cases()
        assert len(cases) == 1
        assert cases[0]["id"] == "eval_001"
        assert cases[0]["question"] == "什么是 LangGraph？"
        assert cases[0]["expected_keywords"] == ["LangGraph", "Agent"]
        assert cases[0]["expected_sources"] == ["note1", "note2"]
        assert cases[0]["min_score"] == 0.8
        assert cases[0]["enabled"] is True

    def test_add_overwrites_on_conflict(self, metadata_store):
        """相同 id 重复添加会覆盖。"""
        metadata_store.add_golden_case("e1", "Q1", expected_keywords=["a"])
        metadata_store.add_golden_case("e1", "Q1-updated", expected_keywords=["b", "c"])

        cases = metadata_store.get_golden_cases()
        assert len(cases) == 1
        assert cases[0]["question"] == "Q1-updated"
        assert cases[0]["expected_keywords"] == ["b", "c"]

    def test_update(self, metadata_store):
        """更新字段。"""
        metadata_store.add_golden_case("e1", "Q1", expected_keywords=["a"], min_score=0.5)
        ok = metadata_store.update_golden_case("e1", min_score=0.9, enabled=False)

        assert ok is True
        cases = metadata_store.get_golden_cases()
        assert cases[0]["min_score"] == 0.9
        assert cases[0]["enabled"] is False

    def test_delete(self, metadata_store):
        """删除。"""
        metadata_store.add_golden_case("e1", "Q1")
        assert metadata_store.delete_golden_case("e1") is True
        assert len(metadata_store.get_golden_cases()) == 0
        # 删除不存在的返回 False
        assert metadata_store.delete_golden_case("e1") is False

    def test_enabled_only_filter(self, metadata_store):
        """enabled_only 过滤。"""
        metadata_store.add_golden_case("e1", "Q1", enabled=True)
        metadata_store.add_golden_case("e2", "Q2", enabled=False)

        all_cases = metadata_store.get_golden_cases()
        assert len(all_cases) == 2

        enabled = metadata_store.get_golden_cases(enabled_only=True)
        assert len(enabled) == 1
        assert enabled[0]["id"] == "e1"


class TestEvalRunsHistory:
    """评估批次历史测试（Phase 5D）。"""

    def test_add_and_get_eval_run(self, metadata_store):
        """记录并查询评估批次。"""
        run_id = metadata_store.add_eval_run(
            run_type="offline", total=5, passed=4, pass_rate=0.8,
            avg_score=0.85, duration_ms=12000,
        )
        assert run_id > 0

        runs = metadata_store.get_eval_runs()
        assert len(runs) == 1
        assert runs[0]["run_type"] == "offline"
        assert runs[0]["total"] == 5
        assert runs[0]["passed"] == 4

    def test_update_eval_run(self, metadata_store):
        """更新批次记录。"""
        run_id = metadata_store.add_eval_run(run_type="judge", total=0)
        metadata_store.update_eval_run(
            run_id, total=3, avg_score=4.2, duration_ms=5000,
        )

        runs = metadata_store.get_eval_runs()
        assert runs[0]["total"] == 3
        assert runs[0]["avg_score"] == 4.2

    def test_eval_runs_ordered_desc(self, metadata_store):
        """批次按时间倒序。"""
        metadata_store.add_eval_run(run_type="offline", total=3, passed=3)
        metadata_store.add_eval_run(run_type="offline", total=5, passed=4)

        runs = metadata_store.get_eval_runs()
        assert runs[0]["total"] == 5  # 后记录的在前
        assert runs[1]["total"] == 3

    def test_filter_by_run_type(self, metadata_store):
        """按类型过滤。"""
        metadata_store.add_eval_run(run_type="offline", total=3)
        metadata_store.add_eval_run(run_type="judge", total=5)

        offline = metadata_store.get_eval_runs(run_type="offline")
        judge = metadata_store.get_eval_runs(run_type="judge")
        assert len(offline) == 1
        assert len(judge) == 1
        assert offline[0]["run_type"] == "offline"

    def test_eval_score_with_run_id(self, metadata_store):
        """eval_score 关联批次 ID。"""
        run_id = metadata_store.add_eval_run(run_type="judge", total=1)
        score_id = metadata_store.add_eval_score(
            "t1", "Q", "A", 4, run_id=run_id,
        )
        assert score_id > 0

        scores = metadata_store.get_eval_scores()
        # run_id 字段存在（get_eval_scores 返回不含 run_id，但写入不报错即可）
        assert len(scores) == 1

    def test_eval_run_with_details(self, metadata_store):
        """批次带 details JSON。"""
        run_id = metadata_store.add_eval_run(
            run_type="offline", total=5, passed=3,
            details={"failed_cases": [{"id": "e1", "score": 0.5}]},
        )
        assert run_id  # add_eval_run 返回新 id
        runs = metadata_store.get_eval_runs()
        assert runs[0]["details"]["failed_cases"][0]["id"] == "e1"


class TestBadCasesCRUD:
    """bad_cases 表 CRUD 测试。"""

    def test_add_and_get(self, metadata_store):
        """新增并查询 bad case。"""
        metadata_store.add_bad_case("t1", "问题", "回答", "user_thumbs_down")

        cases = metadata_store.get_bad_cases()
        assert len(cases) == 1
        assert cases[0]["trace_id"] == "t1"
        assert cases[0]["reason"] == "user_thumbs_down"

    def test_delete(self, metadata_store):
        """删除 bad case。"""
        case_id = metadata_store.add_bad_case("t1", "Q", "A", "error")
        assert metadata_store.delete_bad_case(case_id) is True
        assert len(metadata_store.get_bad_cases()) == 0

    def test_ordered_desc(self, metadata_store):
        """按时间倒序。"""
        metadata_store.add_bad_case("t1", "Q1", "A1", "error")
        metadata_store.add_bad_case("t2", "Q2", "A2", "error")

        cases = metadata_store.get_bad_cases()
        assert cases[0]["trace_id"] == "t2"  # 后记录的在前
        assert cases[1]["trace_id"] == "t1"


class TestSeedGoldenDataset:
    """从 YAML 导入种子数据测试。"""

    def test_seed_imports_from_yaml(self, metadata_store, tmp_path):
        """从 YAML 导入 golden cases 到数据库。"""
        yaml_file = tmp_path / "seed.yaml"
        yaml_file.write_text(
            """
- id: eval_001
  question: "问题1"
  expected_keywords: ["a", "b"]
  expected_sources: ["note1"]
  min_score: 0.7
- id: eval_002
  question: "问题2"
  expected_keywords: ["c"]
  min_score: 0.6
""",
            encoding="utf-8",
        )

        count = seed_golden_dataset(metadata_store, yaml_file)
        assert count == 2

        cases = metadata_store.get_golden_cases()
        assert len(cases) == 2
        assert cases[0]["id"] == "eval_001"
        assert cases[0]["expected_keywords"] == ["a", "b"]
        assert cases[1]["min_score"] == 0.6

    def test_seed_nonexistent_file(self, metadata_store):
        """文件不存在返回 0。"""
        count = seed_golden_dataset(metadata_store, "nonexistent.yaml")
        assert count == 0

    def test_seed_overwrites_existing(self, metadata_store, tmp_path):
        """重复导入会覆盖。"""
        yaml_file = tmp_path / "seed.yaml"
        yaml_file.write_text(
            '- id: e1\n  question: "原问题"\n  expected_keywords: ["a"]\n',
            encoding="utf-8",
        )
        seed_golden_dataset(metadata_store, yaml_file)

        yaml_file.write_text(
            '- id: e1\n  question: "更新问题"\n  expected_keywords: ["b", "c"]\n',
            encoding="utf-8",
        )
        seed_golden_dataset(metadata_store, yaml_file)

        cases = metadata_store.get_golden_cases()
        assert len(cases) == 1
        assert cases[0]["question"] == "更新问题"


class TestEvalRunnerDbLoad:
    """EvalRunner 从数据库加载测试集。"""

    def test_load_from_db(self, metadata_store, vector_store):
        """不传 dataset_path 时从数据库加载。"""
        from brain.eval.runner import EvalRunner

        metadata_store.add_golden_case(
            "e1", "问题1", expected_keywords=["a"], min_score=0.7
        )
        metadata_store.add_golden_case(
            "e2", "问题2", expected_keywords=["b"], min_score=0.6, enabled=False
        )

        runner = EvalRunner(vector_store, metadata_store)
        cases = runner.load_dataset()  # 不传路径，从数据库

        # 只加载 enabled 的
        assert len(cases) == 1
        assert cases[0].id == "e1"

    def test_load_from_yaml_still_works(self, metadata_store, vector_store, tmp_path):
        """传 YAML 路径时从文件加载（向后兼容）。"""
        from brain.eval.runner import EvalRunner

        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text(
            '- id: e1\n  question: "Q"\n  expected_keywords: ["a"]\n  min_score: 0.7\n',
            encoding="utf-8",
        )

        runner = EvalRunner(vector_store, metadata_store)
        cases = runner.load_dataset(yaml_file)
        assert len(cases) == 1
        assert cases[0].id == "e1"
