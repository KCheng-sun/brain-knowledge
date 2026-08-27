"""数据源接入 — 可插拔的数据源适配器"""

from brain.ingestion.sources.bookmark import BookmarkSource
from brain.ingestion.sources.rss import RssSource

__all__ = ["RssSource", "BookmarkSource"]
