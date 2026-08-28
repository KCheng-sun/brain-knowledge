"""MetadataStore 单元测试（同步）。

MetadataStore 基于 PostgreSQL 同步实现（带线程锁），
全部测试为普通 sync 函数。
"""


from brain.models import (
    Connection,
    NoteMetadata,
    NoteStatus,
    RelationType,
    SourceType,
    TagCategory,
)


class TestNotes:
    """Notes CRUD"""

    def test_create_and_get_note(self, metadata_store):
        note = NoteMetadata(
            id="test_001",
            title="测试笔记",
            source_type=SourceType.MARKDOWN,
            source_path="/test/note.md",
            file_hash="abc123",
            content_preview="这是一条测试笔记",
            content_length=100,
            chunk_count=3,
        )
        note_id = metadata_store.create_note(note)
        assert note_id == "test_001"

        fetched = metadata_store.get_note("test_001")
        assert fetched is not None
        assert fetched.title == "测试笔记"
        assert fetched.source_type == SourceType.MARKDOWN

    def test_get_nonexistent_note(self, metadata_store):
        assert metadata_store.get_note("nonexistent") is None

    def test_list_notes(self, metadata_store):
        for i in range(5):
            metadata_store.create_note(
                NoteMetadata(id=f"note_{i}", title=f"笔记 {i}", source_type=SourceType.CLI)
            )
        notes = metadata_store.list_notes(limit=3)
        assert len(notes) == 3

    def test_count_notes(self, metadata_store):
        assert metadata_store.count_notes() == 0
        metadata_store.create_note(
            NoteMetadata(id="count_test", title="计数", source_type=SourceType.CLI)
        )
        assert metadata_store.count_notes() == 1

    def test_soft_delete_note(self, metadata_store):
        metadata_store.create_note(
            NoteMetadata(id="delete_test", title="要删除", source_type=SourceType.CLI)
        )
        metadata_store.delete_note("delete_test", soft=True)

        fetched = metadata_store.get_note("delete_test")
        assert fetched is not None
        assert fetched.status == NoteStatus.DELETED
        # active 列表不含已删除
        assert all(n.id != "delete_test" for n in metadata_store.list_notes())

    def test_note_exists_by_hash(self, metadata_store):
        metadata_store.create_note(
            NoteMetadata(id="dup", title="去重", source_type=SourceType.MARKDOWN,
                         file_hash="hash_123")
        )
        assert metadata_store.note_exists("hash_123") == "dup"
        assert metadata_store.note_exists("no_such_hash") is None

    def test_update_note(self, metadata_store):
        metadata_store.create_note(
            NoteMetadata(id="upd", title="旧标题", source_type=SourceType.CLI)
        )
        metadata_store.update_note("upd", title="新标题")
        assert metadata_store.get_note("upd").title == "新标题"


class TestTags:
    def test_get_or_create_tag_idempotent(self, metadata_store):
        id1 = metadata_store.get_or_create_tag("Python", TagCategory.TOPIC)
        id2 = metadata_store.get_or_create_tag("Python", TagCategory.TOPIC)
        assert id1 == id2

    def test_add_and_get_note_tags(self, metadata_store):
        metadata_store.create_note(
            NoteMetadata(id="tagged", title="有标签", source_type=SourceType.MARKDOWN)
        )
        py_id = metadata_store.get_or_create_tag("Python", TagCategory.TOPIC)
        tut_id = metadata_store.get_or_create_tag("教程", TagCategory.TYPE)
        metadata_store.add_tag_to_note("tagged", py_id, 0.95)
        metadata_store.add_tag_to_note("tagged", tut_id, 0.8)

        tags = metadata_store.get_note_tags("tagged")
        assert {t.name for t in tags} == {"Python", "教程"}


class TestConnections:
    def test_add_and_get_connections(self, metadata_store):
        for nid in ["note_a", "note_b"]:
            metadata_store.create_note(
                NoteMetadata(id=nid, title=nid, source_type=SourceType.CLI)
            )
        conn_id = metadata_store.add_connection(
            Connection(
                source_note_id="note_a",
                target_note_id="note_b",
                relation_type=RelationType.RELATED,
                strength=0.85,
                description="相关",
                is_ai_generated=True,
            )
        )
        assert conn_id is not None
        conns = metadata_store.get_connections("note_a")
        assert len(conns) == 1
        assert conns[0].relation_type == RelationType.RELATED


class TestSessions:
    """会话管理（Phase 3 新增）"""

    def test_create_and_list_sessions(self, metadata_store):
        metadata_store.create_session("s1", "会话一")
        metadata_store.create_session("s2", "会话二")
        sessions = metadata_store.list_sessions()
        assert len(sessions) == 2
        # 按 updated_at 倒序，s2 后建应在前
        assert sessions[0]["id"] == "s2"

    def test_get_session(self, metadata_store):
        metadata_store.create_session("s1", "标题")
        s = metadata_store.get_session("s1")
        assert s is not None and s["title"] == "标题"
        assert metadata_store.get_session("nope") is None

    def test_rename_and_touch_session(self, metadata_store):
        metadata_store.create_session("s1", "旧名")
        metadata_store.rename_session("s1", "新名")
        assert metadata_store.get_session("s1")["title"] == "新名"
        # touch 不应抛异常
        metadata_store.touch_session("s1")

    def test_delete_session(self, metadata_store):
        metadata_store.create_session("s1")
        metadata_store.delete_session("s1")
        assert metadata_store.get_session("s1") is None

    def test_delete_session_cascades_messages(self, metadata_store):
        metadata_store.create_session("s1")
        metadata_store.add_message("s1", "user", "你好")
        metadata_store.delete_session("s1")
        assert metadata_store.count_messages("s1") == 0


class TestMessages:
    def test_add_and_get_messages(self, metadata_store):
        metadata_store.create_session("s1")
        metadata_store.add_message("s1", "user", "问题")
        metadata_store.add_message(
            "s1", "assistant", "回答",
            timeline=[{"kind": "tool", "name": "search_notes", "args": {}, "done": True}],
        )

        messages = metadata_store.get_messages("s1")
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"
        # timeline JSON 正确还原
        assert messages[1]["timeline"][0]["name"] == "search_notes"
        assert messages[1]["timeline"][0]["done"] is True

    def test_messages_ordered_chronologically(self, metadata_store):
        metadata_store.create_session("s1")
        for i in range(3):
            metadata_store.add_message("s1", "user", f"消息{i}")
        ids = [m["id"] for m in metadata_store.get_messages("s1")]
        assert ids == sorted(ids)

    def test_count_messages(self, metadata_store):
        metadata_store.create_session("s1")
        assert metadata_store.count_messages("s1") == 0
        metadata_store.add_message("s1", "user", "x")
        assert metadata_store.count_messages("s1") == 1


class TestKnowledgeFragments:
    """知识片段（HIL 沉淀）"""

    def test_add_and_list_fragments(self, metadata_store):
        metadata_store.add_knowledge_fragment("片段1", "内容A", session_id="s1")
        metadata_store.add_knowledge_fragment("片段2", "内容B")
        fragments = metadata_store.list_knowledge_fragments()
        assert len(fragments) == 2
        # 倒序：片段2 在前
        assert fragments[0]["title"] == "片段2"

    def test_find_similar_fragment(self, metadata_store):
        metadata_store.add_knowledge_fragment("LangGraph 选型", "SqliteSaver")
        found = metadata_store.find_similar_fragment("LangGraph 选型")
        assert found is not None
        assert found["content"] == "SqliteSaver"
        assert metadata_store.find_similar_fragment("不存在") is None

    def test_search_fragments_keyword(self, metadata_store):
        metadata_store.add_knowledge_fragment("Checkpoint 机制", "支持中断恢复")
        metadata_store.add_knowledge_fragment("Embedding 选型", "BGE 模型")
        hits = metadata_store.search_knowledge_fragments("Checkpoint")
        assert len(hits) == 1
        assert hits[0]["title"] == "Checkpoint 机制"

    def test_delete_fragment(self, metadata_store):
        fid = metadata_store.add_knowledge_fragment("待删", "内容")
        assert metadata_store.delete_knowledge_fragment(fid) is True
        assert metadata_store.delete_knowledge_fragment(fid) is False
        assert metadata_store.list_knowledge_fragments() == []


class TestRssFeeds:
    """RSS 订阅源管理"""

    def test_add_list_delete_feed(self, metadata_store):
        feed_id = metadata_store.add_rss_feed("https://example.com/feed.xml")
        feeds = metadata_store.list_rss_feeds()
        assert len(feeds) == 1
        assert feeds[0]["url"] == "https://example.com/feed.xml"

        assert metadata_store.delete_rss_feed(feed_id) is True
        assert metadata_store.delete_rss_feed(feed_id) is False

    def test_entry_dedup(self, metadata_store):
        feed_id = metadata_store.add_rss_feed("https://example.com/feed.xml")
        assert metadata_store.rss_entry_exists(feed_id, "entry-1") is False
        metadata_store.add_rss_entry(feed_id, "entry-1", "标题", "http://x", "2024-01-01")
        assert metadata_store.rss_entry_exists(feed_id, "entry-1") is True

    def test_update_after_fetch(self, metadata_store):
        feed_id = metadata_store.add_rss_feed("https://example.com/feed.xml")
        metadata_store.update_rss_feed_after_fetch(feed_id, "示例博客", 5)
        feed = metadata_store.get_rss_feed(feed_id)
        assert feed["title"] == "示例博客"
        assert feed["entry_count"] == 5
        assert feed["last_fetched_at"] is not None


class TestLogEvent:
    def test_log_event(self, metadata_store):
        metadata_store.create_note(
            NoteMetadata(id="log_test", title="日志", source_type=SourceType.CLI)
        )
        # 不抛异常即通过
        metadata_store.log_event("log_test", "parse", "success", "ok", 10)
