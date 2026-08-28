"""性能回归测试 — 成功指标 NFR2/成功指标4：500+ 笔记保持响应。

在临时库批量摄入 500 条笔记后，验证核心读接口响应时间。
摄入不依赖 LLM（classify/connect 被 mock），500 条应秒级完成。
"""

import hashlib
import time

import pytest
from fastapi.testclient import TestClient


def _mock_embedding(texts: list[str]) -> list[list[float]]:
    result = []
    for text in texts:
        h = hashlib.sha256(text.encode()).digest()
        vec = [(h[i % len(h)] / 255.0) * 2 - 1 for i in range(1024)]
        norm = sum(v * v for v in vec) ** 0.5
        result.append([v / norm for v in vec])
    return result


@pytest.fixture(scope="module")
def bulk_client(tmp_path_factory):
    """500 条笔记的测试客户端（模块级复用，只摄入一次）。

    性能测试只读不写，5 个测试共享同一份数据，避免重复摄入 2500 条。
    """
    import uuid as _uuid

    import psycopg as _psycopg

    import brain.api.deps as deps_module
    import brain.api.server as server_module
    import brain.config as config_module
    from brain.config import AppConfig, DatabaseSettings, StorageSettings

    tmp_path = tmp_path_factory.mktemp("perf_data")
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    test_schema = f"perf_{_uuid.uuid4().hex[:8]}"
    cfg = AppConfig()
    cfg.storage = StorageSettings(
        data_dir=tmp_path / "data",
        notes_dir=tmp_path / "notes",
    )
    cfg.database = DatabaseSettings(
        host="localhost", port=5432, user="postgres",
        password="12345678", database="brain",
    )
    config_module._config = cfg

    # 创建测试 schema，monkeypatch dsn 加 search_path
    _orig_dsn = cfg.database.dsn
    _setup = _psycopg.connect(_orig_dsn, autocommit=True)
    _setup.execute(f"CREATE SCHEMA IF NOT EXISTS {test_schema}")
    _setup.close()
    def _test_dsn(self):
        return f"{_orig_dsn} options='-c search_path={test_schema},public'"
    DatabaseSettings.dsn = property(_test_dsn)

    # 手动 monkeypatch（session 级 fixture 不能用 function 级的 monkeypatch）
    _orig_embed = deps_module.get_embedding_fn
    deps_module.get_embedding_fn = lambda: _mock_embedding

    # mock AI 节点
    from brain.agents.classifier import ClassificationOutput, ClassifierAgent, TypeItem
    from brain.agents.connector import ConnectionOutput, ConnectorAgent

    _orig_classifier = ClassifierAgent.run
    _orig_connector = ConnectorAgent.run
    ClassifierAgent.run = lambda self, **kwargs: ClassificationOutput(
        topics=[], content_type=TypeItem(name="总结/笔记", confidence=0.9)
    )
    ConnectorAgent.run = lambda self, **kwargs: ConnectionOutput(connections=[])

    deps_module.reset_for_test()

    with TestClient(server_module.app) as c:
        # 批量摄入 500 条
        for i in range(500):
            c.post("/api/notes", json={
                "text": f"性能测试笔记 {i}: 关于知识管理的自动化处理流程",
                "title": f"笔记 {i}",
            })
        yield c

    # 还原所有 patch（session 结束）
    DatabaseSettings.dsn = property(lambda self: (
        f"host={self.host} port={self.port} dbname={self.database} "
        f"user={self.user} password={self.password}"
    ))
    deps_module.get_embedding_fn = _orig_embed
    ClassifierAgent.run = _orig_classifier
    ConnectorAgent.run = _orig_connector
    deps_module.reset_for_test()
    # 删除测试 schema
    _cleanup = _psycopg.connect(_orig_dsn, autocommit=True)
    _cleanup.execute(f"DROP SCHEMA IF EXISTS {test_schema} CASCADE")
    _cleanup.close()


class TestPerformance:
    """响应时间上限（宽松阈值，CI 机器性能差异大）"""

    def test_status_under_2s(self, bulk_client):
        t0 = time.perf_counter()
        resp = bulk_client.get("/api/status")
        elapsed = time.perf_counter() - t0
        assert resp.status_code == 200
        assert resp.json()["note_count"] == 500
        assert elapsed < 2.0, f"status 响应 {elapsed:.2f}s 超过 2s"

    def test_search_under_2s(self, bulk_client):
        t0 = time.perf_counter()
        resp = bulk_client.get("/api/search", params={"query": "知识管理", "top_k": 5})
        elapsed = time.perf_counter() - t0
        assert resp.status_code == 200
        assert resp.json()["total"] >= 1
        assert elapsed < 2.0, f"search 响应 {elapsed:.2f}s 超过 2s"

    def test_graph_under_2s(self, bulk_client):
        t0 = time.perf_counter()
        resp = bulk_client.get("/api/graph")
        elapsed = time.perf_counter() - t0
        assert resp.status_code == 200
        assert len(resp.json()["nodes"]) == 500
        assert elapsed < 2.0, f"graph 响应 {elapsed:.2f}s 超过 2s"

    def test_connections_under_2s(self, bulk_client):
        t0 = time.perf_counter()
        resp = bulk_client.get("/api/connections")
        elapsed = time.perf_counter() - t0
        assert resp.status_code == 200
        assert elapsed < 2.0, f"connections 响应 {elapsed:.2f}s 超过 2s"

    def test_review_under_2s(self, bulk_client):
        t0 = time.perf_counter()
        resp = bulk_client.get("/api/review", params={"limit": 20})
        elapsed = time.perf_counter() - t0
        assert resp.status_code == 200
        assert elapsed < 2.0, f"review 响应 {elapsed:.2f}s 超过 2s"
