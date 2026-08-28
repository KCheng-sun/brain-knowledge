"""API 层服务单例管理。

集中持有所有服务实例（懒加载），路由模块通过 get_*() 访问器获取。
避免全局变量散落各处，也消除业务层（如 brain.prompts）反向 import API 层的耦合。

用法：
    from brain.api.deps import get_metadata_store, get_vector_store
    store = get_metadata_store()  # 已初始化则直接返回，否则触发 _init()
"""

from loguru import logger

from brain.config import get_config
from brain.embedding import get_embedding_fn
from brain.ingestion.pipeline import IngestionPipeline
from brain.retrieval import HybridSearcher, build_hybrid_searcher
from brain.storage.metadata import MetadataStore
from brain.storage.vector_store import VectorStore

# ============================================================
# 服务单例（模块级，_init 懒加载）
# ============================================================

_pipeline: IngestionPipeline | None = None
_vector_store: VectorStore | None = None
_metadata_store: MetadataStore | None = None
_hybrid_searcher: HybridSearcher | None = None  # Phase 5F 混合检索器
_checkpointer = None  # LangGraph SqliteSaver——HIL 中断恢复用
_scheduler = None  # TaskScheduler——定时任务调度
_watcher = None  # FileWatcher——文件监听（可经 API 启停）


def _init() -> None:
    """初始化所有服务单例（幂等，已初始化则直接返回）。"""
    global _pipeline, _vector_store, _metadata_store, _hybrid_searcher
    global _checkpointer, _scheduler
    if _metadata_store is not None:
        return
    cfg = get_config()
    embedding_fn = get_embedding_fn()
    _vector_store = VectorStore(persist_dir=cfg.storage.chroma_dir, embedding_fn=embedding_fn)
    _metadata_store = MetadataStore(db_path=cfg.storage.db_path)
    _metadata_store.initialize()
    _pipeline = IngestionPipeline(
        vector_store=_vector_store,
        metadata_store=_metadata_store,
        chunk_size=cfg.ingestion.chunk_size,
        chunk_overlap=cfg.ingestion.chunk_overlap,
    )
    # Phase 5F：组装混合检索器（供 ResearcherAgent 和 /api/search 使用）
    _hybrid_searcher = build_hybrid_searcher(_vector_store, _metadata_store)

    # HIL 中断恢复所需的 checkpointer（thread_id = session_id）
    import sqlite3

    from langgraph.checkpoint.sqlite import SqliteSaver

    checkpoint_path = cfg.storage.data_dir / "checkpoints.db"
    conn = sqlite3.connect(str(checkpoint_path), check_same_thread=False)
    _checkpointer = SqliteSaver(conn)

    # 定时任务调度器
    from brain.services.scheduler import build_default_scheduler

    _scheduler = build_default_scheduler(_pipeline, _metadata_store, _vector_store)
    _scheduler.start()

    # 回填历史知识片段的向量（幂等 upsert，已向量化的不受影响）
    for frag in _metadata_store.list_knowledge_fragments(limit=10000):
        try:
            _vector_store.add_fragment(frag["id"], frag["title"], frag["content"])
        except Exception as e:
            logger.warning(f"片段 #{frag['id']} 向量回填失败: {e}")


# ============================================================
# 访问器（路由模块用这些，自动触发 _init）
# ============================================================

def get_pipeline() -> IngestionPipeline:
    _init()
    assert _pipeline is not None
    return _pipeline


def get_vector_store() -> VectorStore:
    _init()
    assert _vector_store is not None
    return _vector_store


def get_metadata_store() -> MetadataStore:
    _init()
    assert _metadata_store is not None
    return _metadata_store


def get_hybrid_searcher() -> HybridSearcher | None:
    _init()
    return _hybrid_searcher


def get_checkpointer():
    _init()
    return _checkpointer


def get_scheduler():
    _init()
    return _scheduler


def get_watcher():
    """文件监听器（可能为 None，由 watch 路由启停）。"""
    return _watcher


def set_watcher(watcher) -> None:
    """文件监听器由 watch 路由启停时设置。"""
    global _watcher
    _watcher = watcher


def reset_for_test() -> None:
    """重置全部单例（测试 fixture 用）。"""
    global _pipeline, _vector_store, _metadata_store, _hybrid_searcher
    global _checkpointer, _scheduler, _watcher
    _pipeline = None
    _vector_store = None
    _metadata_store = None
    _hybrid_searcher = None
    _checkpointer = None
    _scheduler = None
    _watcher = None
