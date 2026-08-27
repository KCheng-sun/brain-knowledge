"""Phase 4B 存储层新方法测试（FR35/FR36）。

覆盖：
- list_all_tags：标签计数聚合 + category 字段
- remove_tag_from_note：按标签名移除
- delete_connection：按 ID 删除关联
"""

import pytest

from brain.models import Connection, NoteMetadata, RelationType, SourceType, TagCategory


def _make_note(note_id: str, title: str = "测试笔记") -> NoteMetadata:
    return NoteMetadata(
        id=note_id,
        title=title,
        source_type=SourceType.MARKDOWN,
        content_preview="预览内容",
        content_length=10,
    )


@pytest.fixture
def store_with_notes(metadata_store):
    """预置 2 条笔记 + 3 个标签 + 1 条关联的 store。"""
    ms = metadata_store
    ms.create_note(_make_note("n1", "笔记一"))
    ms.create_note(_make_note("n2", "笔记二"))

    # 标签
    tag_python = ms.get_or_create_tag("python", TagCategory.TOPIC)
    tag_ai = ms.get_or_create_tag("ai", TagCategory.TOPIC)
    ms.get_or_create_tag("tutorial", TagCategory.TYPE)

    # n1 关联两个标签，n2 关联一个
    ms.add_tag_to_note("n1", tag_python, confidence=0.9)
    ms.add_tag_to_note("n1", tag_ai, confidence=0.8)
    ms.add_tag_to_note("n2", tag_python, confidence=0.7)

    # 关联
    conn = Connection(
        source_note_id="n1", target_note_id="n2",
        relation_type=RelationType.RELATED, strength=0.6,
    )
    conn_id = ms.add_connection(conn)
    return ms, conn_id


class TestListAllTags:
    def test_returns_all_tags_with_count(self, store_with_notes):
        ms, _ = store_with_notes
        tags = ms.list_all_tags()

        # 3 个标签
        assert len(tags) == 3
        # python 被两个笔记使用
        python = next(t for t in tags if t["name"] == "python")
        assert python["count"] == 2
        assert python["category"] == "topic"
        # ai 和 tutorial 各 1 次
        ai = next(t for t in tags if t["name"] == "ai")
        assert ai["count"] == 1

    def test_ordered_by_count_desc(self, store_with_notes):
        ms, _ = store_with_notes
        tags = ms.list_all_tags()
        counts = [t["count"] for t in tags]
        assert counts == sorted(counts, reverse=True)

    def test_empty_store_returns_empty(self, metadata_store):
        assert metadata_store.list_all_tags() == []


class TestRemoveTagFromNote:
    def test_remove_existing_tag(self, store_with_notes):
        ms, _ = store_with_notes
        ok = ms.remove_tag_from_note("n1", "ai")
        assert ok is True
        # n1 现在只剩 python
        remaining = [t.name for t in ms.get_note_tags("n1")]
        assert "ai" not in remaining
        assert "python" in remaining

    def test_remove_nonexistent_tag_returns_false(self, store_with_notes):
        ms, _ = store_with_notes
        assert ms.remove_tag_from_note("n1", "不存在的标签") is False

    def test_remove_tag_not_on_note_returns_false(self, store_with_notes):
        # tutorial 没关联到 n1
        ms, _ = store_with_notes
        assert ms.remove_tag_from_note("n1", "tutorial") is False

    def test_remove_does_not_delete_tag_definition(self, store_with_notes):
        """移除标签关联后，tags 表里的标签定义仍保留。"""
        ms, _ = store_with_notes
        ms.remove_tag_from_note("n1", "ai")
        # ai 标签定义仍在（n1 移除了，但 tags 表保留）
        tags = ms.list_all_tags()
        assert any(t["name"] == "ai" for t in tags)


class TestDeleteConnection:
    def test_delete_existing_connection(self, store_with_notes):
        ms, conn_id = store_with_notes
        ok = ms.delete_connection(conn_id)
        assert ok is True
        # n1 的关联已删除
        assert ms.get_connections("n1") == []

    def test_delete_nonexistent_returns_false(self, store_with_notes):
        ms, _ = store_with_notes
        assert ms.delete_connection(99999) is False
