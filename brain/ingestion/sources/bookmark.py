"""书签源适配器 — 导入浏览器书签并摄入知识库（Phase 4B FR34）。

支持格式：
  - Chrome 导出：根节点 "roots" 下按文件夹嵌套，children 递归
  - Firefox 导出：平铺数组，带 typeCode (1=folder, 2=bookmark)

职责：
  1. 解析 JSON，递归提取 (title, url) 对
  2. file_hash 基于 URL 计算（同一书签重复导入跳过）
  3. 通过 IngestionPipeline 摄入（source_type=BOOKMARK，走完整流水线）
"""

import hashlib
import json
from pathlib import Path

from loguru import logger

from brain.ingestion.pipeline import IngestionPipeline
from brain.models import SourceType
from brain.storage.metadata import MetadataStore


class BookmarkSource:
    """浏览器书签导入源——解析 JSON 并批量摄入。"""

    def __init__(self, pipeline: IngestionPipeline, metadata_store: MetadataStore):
        self._pipeline = pipeline
        self._store = metadata_store

    def import_file(self, file_path: Path) -> dict:
        """导入书签 JSON 文件。

        Args:
            file_path: Chrome/Firefox 书签导出文件路径

        Returns:
            {"total": n, "success": n, "skipped": n, "failed": n}
        """
        raw = file_path.read_text(encoding="utf-8")
        data = json.loads(raw)
        bookmarks = self._extract_bookmarks(data)

        summary = {"total": len(bookmarks), "success": 0, "skipped": 0, "failed": 0}
        logger.info(f"[bookmark] 解析到 {len(bookmarks)} 个书签，开始摄入")

        for title, url in bookmarks:
            try:
                # 去重：file_hash 必须与流水线内部计算方式一致。
                # ingest_text_sync 内部会把 content 包装为 "# {title}\n\n{content}"，
                # 所以 hash 基于包装后的完整文本计算
                wrapped = f"# {title[:100]}\n\n{url}"
                file_hash = hashlib.sha256(wrapped.encode("utf-8")).hexdigest()
                if self._store.note_exists(file_hash):
                    summary["skipped"] += 1
                    continue

                # content 传纯 URL，标题由 pipeline 包装（保证 file_hash 一致）
                note_id = self._pipeline.ingest_text_sync(
                    url,
                    title=title[:100],
                    source_type=SourceType.BOOKMARK,
                )
                summary["success"] += 1
                logger.debug(f"[bookmark] ✅ {title[:40]} → {note_id}")
            except Exception as e:
                summary["failed"] += 1
                logger.warning(f"[bookmark] 导入失败 {title[:40]}: {e}")

        logger.info(
            f"[bookmark] 导入完成: 成功 {summary['success']}, "
            f"跳过 {summary['skipped']}, 失败 {summary['failed']}"
        )
        return summary

    def _extract_bookmarks(self, data: dict) -> list[tuple[str, str]]:
        """从 Chrome/Firefox JSON 提取 (title, url) 对。

        自动识别格式：
          - Chrome: data["roots"] 存在，递归其下各文件夹的 children
          - Firefox: 顶层有 children 数组，typeCode=2 是书签
        """
        bookmarks: list[tuple[str, str]] = []

        if "roots" in data:
            # Chrome 格式：roots 下每个键是一个文件夹（bookmark_bar/other 等）
            for folder in data["roots"].values():
                if isinstance(folder, dict):
                    self._collect_chrome(folder, bookmarks)
        else:
            # Firefox 格式：顶层就是节点，递归 children
            self._collect_firefox(data, bookmarks)

        return bookmarks

    @staticmethod
    def _collect_chrome(node: dict, out: list[tuple[str, str]]) -> None:
        """递归收集 Chrome 书签节点。"""
        # type=url 是书签，type=folder 是文件夹
        if node.get("type") == "url" and node.get("url"):
            title = node.get("name", "").strip() or "无标题书签"
            out.append((title, node["url"]))

        for child in node.get("children", []) or []:
            if isinstance(child, dict):
                BookmarkSource._collect_chrome(child, out)

    @staticmethod
    def _collect_firefox(node: dict, out: list[tuple[str, str]]) -> None:
        """递归收集 Firefox 书签节点。typeCode: 1=folder, 2=bookmark."""
        if node.get("typeCode") == 2 and node.get("uri"):
            title = node.get("title", "").strip() or "无标题书签"
            out.append((title, node["uri"]))

        for child in node.get("children", []) or []:
            if isinstance(child, dict):
                BookmarkSource._collect_firefox(child, out)
