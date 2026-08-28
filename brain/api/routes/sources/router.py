"""数据源业务域 API 路由（文件监听 / RSS / 书签导入）。

端点:
  GET    /api/watch                  — 文件监听状态
  POST   /api/watch/start            — 启动文件监听
  POST   /api/watch/stop             — 停止文件监听
  GET    /api/rss                    — 列出 RSS 订阅源
  POST   /api/rss                    — 添加并拉取
  POST   /api/rss/fetch             — 拉取全部
  DELETE /api/rss/{feed_id}         — 删除订阅源
  POST   /api/bookmarks/import       — 导入浏览器书签
"""

import tempfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from loguru import logger

from brain.api.deps import get_metadata_store, get_pipeline, get_watcher, set_watcher
from brain.api.routes.sources.models import (
    BookmarkImportResponse,
    RssAddRequest,
    RssFetchResponse,
    WatchStatusResponse,
)
from brain.config import get_config

router = APIRouter(prefix="/api", tags=["sources"])


# ============================================================
# 文件监听
# ============================================================

@router.get("/watch", response_model=WatchStatusResponse)
def watch_status():
    """查询文件监听状态。"""
    cfg = get_config()
    watcher = get_watcher()
    if watcher is not None and watcher.is_running():
        return WatchStatusResponse(
            running=True,
            watch_dir=str(watcher.watch_dir),
            recent_events=watcher.get_recent_events(),
        )
    return WatchStatusResponse(
        running=False,
        watch_dir=str(cfg.storage.notes_dir),
        recent_events=[],
    )


@router.post("/watch/start", response_model=WatchStatusResponse)
def watch_start():
    """启动文件监听（后台线程）。"""
    watcher = get_watcher()
    if watcher is not None and watcher.is_running():
        return WatchStatusResponse(
            running=True,
            watch_dir=str(watcher.watch_dir),
            recent_events=watcher.get_recent_events(),
        )

    from brain.ingestion.watcher import FileWatcher

    cfg = get_config()
    pipeline = get_pipeline()
    watch_dir = cfg.storage.notes_dir
    watch_dir.mkdir(parents=True, exist_ok=True)

    def _on_file(file_path):
        try:
            note_id = pipeline.ingest_file_sync(file_path)
            watcher.record_event(file_path.name, note_id)
            logger.info(f"[watch] ✅ {file_path.name} → {note_id}")
        except Exception as e:
            logger.warning(f"[watch] ❌ {file_path.name}: {e}")

    new_watcher = FileWatcher(
        watch_dir=watch_dir,
        ingest_callback=_on_file,
        debounce_seconds=cfg.ingestion.debounce_seconds,
    )
    new_watcher.start()
    set_watcher(new_watcher)

    return WatchStatusResponse(
        running=True,
        watch_dir=str(watch_dir),
        recent_events=[],
    )


@router.post("/watch/stop", response_model=WatchStatusResponse)
def watch_stop():
    """停止文件监听。"""
    watcher = get_watcher()
    if watcher is not None:
        watcher.stop()
        set_watcher(None)

    cfg = get_config()
    return WatchStatusResponse(
        running=False,
        watch_dir=str(cfg.storage.notes_dir),
        recent_events=[],
    )


# ============================================================
# RSS 订阅
# ============================================================

@router.get("/rss")
def rss_list():
    """列出全部 RSS 订阅源。"""
    return get_metadata_store().list_rss_feeds()


@router.post("/rss", response_model=RssFetchResponse)
def rss_add_and_fetch(req: RssAddRequest):
    """添加订阅源并立即拉取一次。"""
    from brain.ingestion.sources.rss import RssSource

    pipeline = get_pipeline()
    ms = get_metadata_store()
    source = RssSource(pipeline, ms)
    feed_id = source.add_feed(req.url)
    new_count = source.fetch_feed(feed_id)

    return RssFetchResponse(
        feeds_checked=1,
        new_entries=new_count,
        errors=[],
    )


@router.post("/rss/fetch", response_model=RssFetchResponse)
def rss_fetch_all():
    """拉取所有订阅源的新文章。"""
    from brain.ingestion.sources.rss import RssSource

    source = RssSource(get_pipeline(), get_metadata_store())
    summary = source.fetch_all()
    return RssFetchResponse(**summary)


@router.delete("/rss/{feed_id}")
def rss_delete(feed_id: int):
    """删除 RSS 订阅源。"""
    ms = get_metadata_store()
    if not ms.delete_rss_feed(feed_id):
        raise HTTPException(status_code=404, detail="订阅源不存在")
    return {"ok": True}


# ============================================================
# 书签导入
# ============================================================

@router.post("/bookmarks/import", response_model=BookmarkImportResponse)
def import_bookmarks(file: UploadFile = File(...)):
    """导入浏览器书签 JSON 文件（FR34）。支持 Chrome/Firefox 格式。"""
    from brain.ingestion.sources import BookmarkSource

    pipeline = get_pipeline()
    ms = get_metadata_store()
    # 保存上传文件到临时路径
    suffix = Path(file.filename or "bookmarks.json").suffix or ".json"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(file.file.read())
        tmp_path = Path(tmp.name)

    try:
        source = BookmarkSource(pipeline, ms)
        summary = source.import_file(tmp_path)
        return BookmarkImportResponse(**summary)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()
