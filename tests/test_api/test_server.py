"""API 层集成测试 — FastAPI TestClient + mock embedding。

服务模块用模块级单例，测试需:
  1. 重置 brain.api.server 的全局单例（指向临时目录）
  2. mock get_embedding_fn（避免真实 SiliconFlow/本地模型调用）
  3. mock LLM 调用（问答端点不真实调 DeepSeek）
"""

import hashlib

import pytest
from fastapi.testclient import TestClient


def _mock_embedding(texts: list[str]) -> list[list[float]]:
    """确定性 mock embedding（1024 维，与 BGE-large-zh 一致）。"""
    result = []
    for text in texts:
        h = hashlib.sha256(text.encode()).digest()
        vec = [(h[i % len(h)] / 255.0) * 2 - 1 for i in range(1024)]
        norm = sum(v * v for v in vec) ** 0.5
        result.append([v / norm for v in vec])
    return result


@pytest.fixture
def client(tmp_path, monkeypatch):
    """构造指向临时目录的测试客户端。"""
    import uuid as _uuid

    import brain.api.deps as deps_module
    import brain.api.server as server_module
    import brain.config as config_module

    # 1. 用独立 schema 隔离测试（每个测试一个临时 schema，测完删除）
    from brain.config import AppConfig, DatabaseSettings, StorageSettings

    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    test_schema = f"test_{_uuid.uuid4().hex[:8]}"
    cfg = AppConfig()
    cfg.storage = StorageSettings(
        data_dir=tmp_path / "data",
        notes_dir=tmp_path / "notes",
    )
    # 连同一个 Postgres，但用独立 schema 隔离数据
    cfg.database = DatabaseSettings(
        host="localhost", port=5432, user="postgres",
        password="12345678", database="brain",
    )
    monkeypatch.setattr(config_module, "_config", cfg)

    # 创建测试 schema（连接初始化时 MetadataStore/VectorStore 会在此 schema 建表）
    import psycopg as _psycopg
    _setup_conn = _psycopg.connect(cfg.database.dsn, autocommit=True)
    _setup_conn.execute(f"CREATE SCHEMA IF NOT EXISTS {test_schema}")
    _setup_conn.execute(f"SET search_path TO {test_schema}")
    _setup_conn.close()
    # 通过连接参数指定 search_path（每个新连接都生效）
    # psycopg 的 dsn 不支持 options，用 connection_factory 太复杂
    # 改为 monkeypatch dsn 加 options 参数
    _orig_dsn = cfg.database.dsn
    # Postgres 支持 options=-c search_path=test_xxx
    _orig_dsn_prop = DatabaseSettings.dsn.fget
    def _test_dsn(self):
        return f"{_orig_dsn} options='-c search_path={test_schema},public'"
    monkeypatch.setattr(DatabaseSettings, "dsn", property(_test_dsn))

    # 2. mock embedding 函数（deps._init 会调用它）
    monkeypatch.setattr(deps_module, "get_embedding_fn", lambda: _mock_embedding)

    # 3. mock 摄入流水线的 AI 节点（classify/connect），避免真实 LLM 调用
    from brain.agents.classifier import ClassificationOutput, ClassifierAgent, TypeItem
    from brain.agents.connector import ConnectionOutput, ConnectorAgent

    monkeypatch.setattr(
        ClassifierAgent,
        "run",
        lambda self, **kwargs: ClassificationOutput(
            topics=[], content_type=TypeItem(name="总结/笔记", confidence=0.9)
        ),
    )
    monkeypatch.setattr(
        ConnectorAgent,
        "run",
        lambda self, **kwargs: ConnectionOutput(connections=[]),
    )

    # 4. 重置服务单例（通过 deps.reset_for_test 清零，路由通过 deps 访问器读取）
    deps_module.reset_for_test()

    with TestClient(server_module.app) as c:
        yield c

    # 清理：重置单例 + 删除测试 schema
    deps_module.reset_for_test()
    _cleanup_conn = _psycopg.connect(_orig_dsn, autocommit=True)
    _cleanup_conn.execute(f"DROP SCHEMA IF EXISTS {test_schema} CASCADE")
    _cleanup_conn.close()


class TestNotesAPI:
    def test_add_note(self, client):
        resp = client.post("/api/notes", json={"text": "这是一条测试笔记", "title": "测试"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["note_id"]
        assert data["message"] == "摄入成功"

    def test_add_note_empty_text_rejected(self, client):
        resp = client.post("/api/notes", json={"text": ""})
        assert resp.status_code == 422  # Pydantic 校验失败


class TestSearchAPI:
    def test_search_after_ingest(self, client):
        client.post("/api/notes", json={"text": "LangGraph checkpoint 机制详解", "title": "LG"})
        client.post("/api/notes", json={"text": "Python 异步编程指南", "title": "Py"})

        resp = client.get("/api/search", params={"query": "checkpoint", "top_k": 5})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        assert "checkpoint" in data["results"][0]["content_preview"] or "LG" == data["results"][0]["title"]

    def test_search_empty_query_rejected(self, client):
        resp = client.get("/api/search", params={"query": ""})
        assert resp.status_code == 422


class TestSessionsAPI:
    def test_create_and_list_sessions(self, client):
        resp = client.post("/api/sessions", json={"title": "测试会话"})
        assert resp.status_code == 200
        session_id = resp.json()["id"]

        resp = client.get("/api/sessions")
        assert resp.status_code == 200
        assert any(s["id"] == session_id for s in resp.json())

    def test_session_messages_empty(self, client):
        resp = client.post("/api/sessions", json={"title": "空会话"})
        session_id = resp.json()["id"]
        resp = client.get(f"/api/sessions/{session_id}/messages")
        assert resp.status_code == 200
        assert resp.json()["messages"] == []

    def test_session_not_found(self, client):
        resp = client.get("/api/sessions/nonexistent/messages")
        assert resp.status_code == 404

    def test_delete_session(self, client):
        resp = client.post("/api/sessions", json={"title": "待删"})
        session_id = resp.json()["id"]
        resp = client.delete(f"/api/sessions/{session_id}")
        assert resp.status_code == 200
        # 删除后列表为空
        resp = client.get("/api/sessions")
        assert resp.json() == []


class TestFragmentsAPI:
    def test_list_fragments_empty(self, client):
        resp = client.get("/api/fragments")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_fragments_after_ingest(self, client):
        # 直接经存储层写入（HIL 流程在问答中触发，此处只测 API 读/删）
        import brain.api.server as server_module

        server_module._metadata_store.add_knowledge_fragment("测试片段", "内容", session_id="s1")

        resp = client.get("/api/fragments")
        assert resp.status_code == 200
        fragments = resp.json()
        assert len(fragments) == 1
        assert fragments[0]["title"] == "测试片段"

        fid = fragments[0]["id"]
        resp = client.delete(f"/api/fragments/{fid}")
        assert resp.status_code == 200

        assert client.get("/api/fragments").json() == []

    def test_delete_nonexistent_fragment(self, client):
        resp = client.delete("/api/fragments/9999")
        assert resp.status_code == 404


class TestRssAPI:
    def test_list_rss_empty(self, client):
        resp = client.get("/api/rss")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_add_rss_feed(self, client, monkeypatch):
        """添加订阅源——mock fetch_feed 避免真实网络请求。"""
        from brain.ingestion.sources.rss import RssSource

        monkeypatch.setattr(RssSource, "fetch_feed", lambda self, feed_id, limit=10: 0)

        resp = client.post("/api/rss", json={"url": "https://example.com/feed.xml"})
        assert resp.status_code == 200
        assert resp.json()["new_entries"] == 0

        feeds = client.get("/api/rss").json()
        assert len(feeds) == 1
        assert feeds[0]["url"] == "https://example.com/feed.xml"

    def test_delete_rss_feed(self, client):
        import brain.api.server as server_module

        feed_id = server_module._metadata_store.add_rss_feed("https://example.com/feed.xml")
        resp = client.delete(f"/api/rss/{feed_id}")
        assert resp.status_code == 200
        assert client.get("/api/rss").json() == []


class TestWatchAPI:
    def test_watch_status_stopped(self, client):
        resp = client.get("/api/watch")
        assert resp.status_code == 200
        assert resp.json()["running"] is False

    def test_watch_start_stop(self, client):
        resp = client.post("/api/watch/start")
        assert resp.status_code == 200
        assert resp.json()["running"] is True

        resp = client.get("/api/watch")
        assert resp.json()["running"] is True

        resp = client.post("/api/watch/stop")
        assert resp.status_code == 200
        assert resp.json()["running"] is False


class TestStatusAPI:
    def test_status_empty(self, client):
        resp = client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["note_count"] == 0
        assert data["chunk_count"] == 0

    def test_status_after_ingest(self, client):
        client.post("/api/notes", json={"text": "测试笔记内容"})
        data = client.get("/api/status").json()
        assert data["note_count"] == 1
        assert data["chunk_count"] >= 1


class TestTagsAPI:
    """Phase 4B FR35：标签浏览 API。"""

    def test_list_tags_empty(self, client):
        resp = client.get("/api/tags")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_tags_after_ingest(self, client):
        # 摄入笔记后（mock classifier 会生成标签）查询
        client.post("/api/notes", json={"text": "Python 异步编程", "title": "Py"})
        resp = client.get("/api/tags")
        assert resp.status_code == 200
        data = resp.json()
        # mock classifier 返回空 topics，可能无标签；只要接口正常返回列表即可
        assert isinstance(data, list)


class TestNoteEditAPI:
    """Phase 4B FR36：笔记编辑 API。"""

    def test_edit_nonexistent_note_returns_404(self, client):
        resp = client.patch("/api/notes/nonexistent", json={"title": "新标题"})
        assert resp.status_code == 404

    def test_edit_note_title(self, client):
        # 先添加笔记
        add_resp = client.post("/api/notes", json={"text": "测试内容", "title": "旧标题"})
        note_id = add_resp.json()["note_id"]

        # 修改标题
        resp = client.patch(f"/api/notes/{note_id}", json={"title": "新标题"})
        assert resp.status_code == 200
        assert "title" in resp.json()["changed"]

    def test_edit_note_add_tags(self, client):
        add_resp = client.post("/api/notes", json={"text": "测试内容", "title": "T"})
        note_id = add_resp.json()["note_id"]

        resp = client.patch(
            f"/api/notes/{note_id}",
            json={"add_tags": ["python", "ai"]},
        )
        assert resp.status_code == 200
        assert "+2tags" in resp.json()["changed"]

    def test_edit_note_remove_tag(self, client):
        add_resp = client.post("/api/notes", json={"text": "测试内容", "title": "T"})
        note_id = add_resp.json()["note_id"]
        # 先加标签
        client.patch(f"/api/notes/{note_id}", json={"add_tags": ["python"]})
        # 再移除
        resp = client.patch(f"/api/notes/{note_id}", json={"remove_tags": ["python"]})
        assert resp.status_code == 200


class TestConnectionDeleteAPI:
    """Phase 4B FR36：关联删除 API。"""

    def test_delete_nonexistent_connection_returns_404(self, client):
        resp = client.delete("/api/connections/99999")
        assert resp.status_code == 404


class TestBookmarkImportAPI:
    """Phase 4B FR34：书签导入 API。"""

    def test_import_chrome_bookmarks(self, client, tmp_path):
        import json

        data = {"roots": {"bar": {"children": [
            {"type": "url", "name": "Google", "url": "https://google.com"},
        ]}}}
        bookmark_file = tmp_path / "bookmarks.json"
        bookmark_file.write_text(json.dumps(data), encoding="utf-8")

        with open(bookmark_file, "rb") as f:
            resp = client.post(
                "/api/bookmarks/import",
                files={"file": ("bookmarks.json", f, "application/json")},
            )

        assert resp.status_code == 200
        result = resp.json()
        assert result["total"] == 1
        assert result["success"] == 1

    def test_import_firefox_bookmarks(self, client, tmp_path):
        import json

        data = {"children": [
            {"typeCode": 2, "title": "MDN", "uri": "https://developer.mozilla.org"},
        ]}
        bookmark_file = tmp_path / "bookmarks.json"
        bookmark_file.write_text(json.dumps(data), encoding="utf-8")

        with open(bookmark_file, "rb") as f:
            resp = client.post(
                "/api/bookmarks/import",
                files={"file": ("bookmarks.json", f, "application/json")},
            )

        assert resp.status_code == 200
        assert resp.json()["success"] == 1


class TestHILInterrupt:
    """HIL 中断的多 proposals 场景测试。

    验证 DeepSeek 一次提议多个知识片段时，interrupt 事件能完整传递全部
    action_requests，避免恢复时 decisions 数量不匹配报错。
    """

    def test_interrupt_with_multiple_proposals(self, client, monkeypatch):
        """中断含 2 个 action_requests 时，SSE 应返回 2 个 proposals。"""
        from brain.agents.researcher import ResearcherAgent

        # mock research_stream：yield 一个含 2 个 action_requests 的 interrupt
        def fake_research_stream(self, question, session_id, history, memory, checkpointer=None, trace_id=None):
            yield {"type": "session", "session_id": session_id}
            yield {"type": "token", "content": "我发现了两个值得保存的片段。"}
            yield {
                "type": "interrupt",
                "request": {
                    "action_requests": [
                        {
                            "name": "propose_knowledge",
                            "args": {"title": "片段A", "content": "内容A"},
                            "description": "提议保存知识片段",
                        },
                        {
                            "name": "propose_knowledge",
                            "args": {"title": "片段B", "content": "内容B"},
                            "description": "提议保存知识片段",
                        },
                    ],
                },
            }

        monkeypatch.setattr(ResearcherAgent, "research_stream", fake_research_stream)

        resp = client.post(
            "/api/ask/stream",
            json={"question": "测试多片段中断", "session_id": None},
        )
        assert resp.status_code == 200

        # 解析 SSE 事件
        events = []
        for line in resp.text.split("\n"):
            if line.startswith("data: "):
                import json

                events.append(json.loads(line[6:]))

        # 找到 interrupt 事件
        interrupt_event = next((e for e in events if e["type"] == "interrupt"), None)
        assert interrupt_event is not None, "应收到 interrupt 事件"
        assert interrupt_event["session_id"]  # 应携带 session_id

        # 核心断言：proposals 应含 2 项（而非旧的只取第一个）
        proposals = interrupt_event.get("proposals", [])
        assert len(proposals) == 2, f"应返回 2 个 proposals，实际 {len(proposals)}"
        assert proposals[0]["args"]["title"] == "片段A"
        assert proposals[1]["args"]["title"] == "片段B"

    def test_interrupt_with_single_proposal_still_works(self, client, monkeypatch):
        """单个 proposal 的回归测试（确保向后兼容）。"""
        from brain.agents.researcher import ResearcherAgent

        def fake_research_stream(self, question, session_id, history, memory, checkpointer=None, trace_id=None):
            yield {"type": "session", "session_id": session_id}
            yield {
                "type": "interrupt",
                "request": {
                    "action_requests": [
                        {
                            "name": "propose_knowledge",
                            "args": {"title": "单个片段", "content": "内容"},
                            "description": "提议保存",
                        },
                    ],
                },
            }

        monkeypatch.setattr(ResearcherAgent, "research_stream", fake_research_stream)

        resp = client.post(
            "/api/ask/stream",
            json={"question": "测试单片段中断", "session_id": None},
        )
        assert resp.status_code == 200

        import json

        events = [
            json.loads(line[6:])
            for line in resp.text.split("\n")
            if line.startswith("data: ")
        ]
        interrupt_event = next(e for e in events if e["type"] == "interrupt")
        proposals = interrupt_event.get("proposals", [])
        assert len(proposals) == 1
        assert proposals[0]["args"]["title"] == "单个片段"
