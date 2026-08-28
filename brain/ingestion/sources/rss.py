"""RSS 源适配器 — 拉取订阅源并摄入知识库。

职责:
  1. feedparser 拉取并解析 RSS/Atom
  2. 条目去重（rss_entries 表按 entry_id 判重）
  3. 通过 IngestionPipeline 把新条目摄入知识库（走完整流水线: 解析→分块→嵌入→分类→关联）
"""


import feedparser
import requests
from loguru import logger

from brain.ingestion.pipeline import IngestionPipeline
from brain.storage.metadata import MetadataStore


class RssSource:
    """RSS 订阅源——定时拉取文章并自动摄入。"""

    def __init__(self, pipeline: IngestionPipeline, metadata_store: MetadataStore):
        self._pipeline = pipeline
        self._store = metadata_store

    def add_feed(self, url: str) -> int:
        """添加订阅源。返回 feed_id。"""
        feed_id = self._store.add_rss_feed(url)
        logger.info(f"[rss] 已添加订阅源: {url}")
        return feed_id

    def fetch_all(self, limit_per_feed: int = 10) -> dict:
        """拉取所有订阅源的新条目。

        Returns:
            {"feeds_checked": n, "new_entries": n, "errors": [...]}
        """
        feeds = self._store.list_rss_feeds()
        summary = {"feeds_checked": len(feeds), "new_entries": 0, "errors": []}

        for feed in feeds:
            try:
                count = self.fetch_feed(feed["id"], limit=limit_per_feed)
                summary["new_entries"] += count
            except Exception as e:
                logger.warning(f"[rss] 源 {feed['url']} 拉取失败: {e}")
                summary["errors"].append(f"{feed['url']}: {e}")

        return summary

    def fetch_feed(self, feed_id: int, limit: int = 10) -> int:
        """拉取单个订阅源的新条目并摄入。返回新条目数。

        Raises:
            ValueError: 订阅源不存在 / 网络拉取失败 / 解析失败
        """
        feed = self._store.get_rss_feed(feed_id)
        if feed is None:
            raise ValueError(f"订阅源不存在: {feed_id}")

        url = feed["url"]
        logger.info(f"[rss] 拉取: {url}")

        # 用 requests 预拉取（带 UA + 超时），避免 feedparser 直连卡死或被拒
        headers = {"User-Agent": "Brain/1.0 (personal knowledge management)"}
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            content = resp.content
        except requests.exceptions.Timeout:
            raise ValueError(f"拉取超时（15秒），网络不通或源响应过慢: {url}") from None
        except requests.exceptions.ConnectionError as e:
            raise ValueError(f"连接失败，可能网络受限或源不可达: {url}（{e.args[0] if e.args else e}）") from None
        except requests.exceptions.HTTPError:
            raise ValueError(f"源返回 HTTP {resp.status_code}: {url}") from None
        except requests.exceptions.RequestException as e:
            raise ValueError(f"拉取失败: {url}（{e}）") from None

        parsed = feedparser.parse(content)

        if parsed.bozo and not parsed.entries:
            raise ValueError(f"解析失败: {parsed.bozo_exception}")

        feed_title = parsed.feed.get("title", "")[:100]
        new_count = 0

        for entry in parsed.entries[:limit]:
            entry_id = entry.get("id") or entry.get("link") or entry.get("title", "")
            if not entry_id:
                continue

            title = entry.get("title", "无标题").strip()
            link = entry.get("link", "")
            published = entry.get("published", "") or entry.get("updated", "")

            # 构建笔记正文：优先取 content（完整正文），回退 summary（摘要）
            import re

            content_field = entry.get("content", [])
            if content_field and content_field[0].get("value"):
                body_text = content_field[0]["value"]
            else:
                body_text = entry.get("summary", "")
            # 去掉 HTML 标签
            body_text = re.sub(r"<[^>]+>", "", body_text).strip()

            # feed 内容太短（< 500 字）且有原文链接 → 抓网页全文
            if len(body_text) < 500 and link:
                fetched = self._fetch_full_text(link)
                if fetched:
                    body_text = fetched

            # 去重：已处理过的条目跳过摄入，但回填缺失的正文
            existing_content = self._store.get_rss_entry_content(feed_id, entry_id)
            if existing_content is not None:
                # 已存在：content 为空才回填（不重新摄入笔记）
                if not existing_content and body_text:
                    self._store.update_rss_entry_content(feed_id, entry_id, body_text)
                    logger.info(f"[rss] ✏️ 回填正文: {title[:40]}")
                continue

            content_parts = [title]
            if body_text:
                content_parts.append(body_text)
            if link:
                content_parts.append(f"原文链接: {link}")
            content = "\n\n".join(content_parts)

            # 摄入知识库（走完整流水线）
            try:
                note_id = self._pipeline.ingest_text_sync(
                    content,
                    title=f"[RSS] {title[:50]}",
                )
                self._store.add_rss_entry(
                    feed_id, entry_id, title, link, published, note_id, body_text
                )
                new_count += 1
                logger.info(f"[rss] ✅ {title[:40]} → {note_id}")
            except Exception as e:
                logger.warning(f"[rss] 条目摄入失败 {title[:40]}: {e}")

        self._store.update_rss_feed_after_fetch(feed_id, feed_title, new_count)
        return new_count

    @staticmethod
    def _fetch_full_text(url: str) -> str:
        """抓取网页正文（当 feed 只提供短摘要时补充全文）。

        用 trafilatura 从 HTML 提取正文，失败返回空字符串（不阻塞摄入）。
        """
        try:
            import trafilatura

            resp = requests.get(
                url,
                headers={"User-Agent": "Brain/1.0 (personal knowledge management)"},
                timeout=15,
            )
            resp.raise_for_status()
            text = trafilatura.extract(resp.text)
            return text or ""
        except Exception as e:
            logger.debug(f"[rss] 全文抓取失败 {url}: {e}")
            return ""

    def list_feeds(self) -> list[dict]:
        return self._store.list_rss_feeds()

    def remove_feed(self, feed_id: int) -> bool:
        return self._store.delete_rss_feed(feed_id)
