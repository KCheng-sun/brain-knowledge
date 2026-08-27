"""Phase 4B 书签导入测试（FR34）。

覆盖：
- Chrome 格式解析（嵌套 children）
- Firefox 格式解析（typeCode 平铺）
- 基于 URL 去重
- source_type=BOOKMARK 写入
- 导入统计
"""

import json
from pathlib import Path

import pytest

from brain.ingestion.pipeline import IngestionPipeline
from brain.ingestion.sources.bookmark import BookmarkSource
from brain.models import SourceType


@pytest.fixture
def pipeline(vector_store, metadata_store, monkeypatch):
    """构造真实 pipeline，但 mock 掉 AI 节点（避免 LLM 调用）。"""
    from brain.agents.classifier import ClassificationOutput, ClassifierAgent, TypeItem
    from brain.agents.connector import ConnectionOutput, ConnectorAgent

    monkeypatch.setattr(
        ClassifierAgent, "run",
        lambda self, **kwargs: ClassificationOutput(
            topics=[], content_type=TypeItem(name="总结/笔记", confidence=0.9)
        ),
    )
    monkeypatch.setattr(
        ConnectorAgent, "run",
        lambda self, **kwargs: ConnectionOutput(connections=[]),
    )
    return IngestionPipeline(
        vector_store=vector_store,
        metadata_store=metadata_store,
    )


@pytest.fixture
def source(pipeline, metadata_store):
    return BookmarkSource(pipeline, metadata_store)


def _write_json(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "bookmarks.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


class TestChromeFormat:
    def test_parses_nested_children(self, source, tmp_path):
        """Chrome 格式：roots 下嵌套文件夹递归提取。"""
        data = {
            "roots": {
                "bookmark_bar": {
                    "children": [
                        {"type": "url", "name": "Google", "url": "https://google.com"},
                        {"type": "folder", "name": "开发", "children": [
                            {"type": "url", "name": "GitHub", "url": "https://github.com"},
                        ]},
                    ]
                },
                "other": {
                    "children": [
                        {"type": "url", "name": "YouTube", "url": "https://youtube.com"},
                    ]
                },
            }
        }
        path = _write_json(tmp_path, data)

        summary = source.import_file(path)

        assert summary["total"] == 3
        assert summary["success"] == 3
        assert summary["skipped"] == 0

    def test_skips_folder_nodes_without_url(self, source, tmp_path):
        """type=folder 的节点不提取为书签。"""
        data = {"roots": {"bar": {"children": [
            {"type": "folder", "name": "空文件夹", "children": []},
            {"type": "url", "name": "有效书签", "url": "https://example.com"},
        ]}}}
        path = _write_json(tmp_path, data)

        summary = source.import_file(path)
        assert summary["total"] == 1


class TestFirefoxFormat:
    def test_parses_typecode_entries(self, source, tmp_path):
        """Firefox 格式：typeCode=2 是书签，typeCode=1 是文件夹。"""
        data = {
            "children": [
                {"typeCode": 2, "title": "MDN", "uri": "https://developer.mozilla.org"},
                {"typeCode": 1, "title": "文件夹", "children": [
                    {"typeCode": 2, "title": "Stack Overflow", "uri": "https://stackoverflow.com"},
                ]},
            ]
        }
        path = _write_json(tmp_path, data)

        summary = source.import_file(path)

        assert summary["total"] == 2
        assert summary["success"] == 2


class TestDeduplication:
    def test_same_url_skipped_on_second_import(self, source, tmp_path):
        """基于 URL 的 file_hash 去重，重复导入跳过。"""
        data = {"roots": {"bar": {"children": [
            {"type": "url", "name": "Google", "url": "https://google.com"},
        ]}}}
        path = _write_json(tmp_path, data)

        # 第一次导入
        s1 = source.import_file(path)
        assert s1["success"] == 1
        assert s1["skipped"] == 0

        # 第二次导入同一书签
        s2 = source.import_file(path)
        assert s2["success"] == 0
        assert s2["skipped"] == 1


class TestSourceType:
    def test_note_has_bookmark_source_type(self, source, pipeline, metadata_store, tmp_path):
        """导入的书签笔记 source_type 应为 BOOKMARK。"""
        data = {"roots": {"bar": {"children": [
            {"type": "url", "name": "测试书签", "url": "https://test.com/unique"},
        ]}}}
        path = _write_json(tmp_path, data)

        source.import_file(path)

        # 查最近创建的笔记
        notes = metadata_store.list_notes(limit=10)
        bookmark_notes = [n for n in notes if n.source_type == SourceType.BOOKMARK]
        assert len(bookmark_notes) == 1
        assert "测试书签" in bookmark_notes[0].title


class TestErrorHandling:
    def test_invalid_json_raises(self, source, tmp_path):
        """无效 JSON 文件应抛异常。"""
        path = tmp_path / "bad.json"
        path.write_text("not a json", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            source.import_file(path)
