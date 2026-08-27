"""Brain REST API — FastAPI 后端。

启动: brain ui  或  uvicorn brain.api.server:app

端点:
  POST   /api/notes          — 添加笔记
  POST   /api/ingest         — 上传 Markdown 文件
  GET    /api/search         — 语义搜索
  POST   /api/ask            — 深度问答（DeepAgents）
  GET    /api/status         — 知识库统计
  GET    /api/connections    — 查看关联
  GET    /api/digest         — 每日/每周摘要
  GET    /api/review         — 复习提醒
"""

import tempfile
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from pydantic import BaseModel, Field

from brain.agents.researcher import ResearcherAgent
from brain.config import get_config
from brain.embedding import get_embedding_fn
from brain.ingestion.pipeline import IngestionPipeline
from brain.retrieval import HybridSearcher, build_hybrid_searcher
from brain.services.digest import DigestService
from brain.services.review import ReviewService
from brain.storage.metadata import MetadataStore
from brain.storage.vector_store import VectorStore

# ============================================================
# FastAPI 应用
# ============================================================

# ============================================================
# 应用生命周期——lifespan 上下文管理器（替代废弃的 @app.on_event）
# ============================================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化服务，关闭时可放清理逻辑。"""
    _init()
    yield
    # shutdown：调度器停止等清理可放这里（当前由进程退出回收）


app = FastAPI(title="Brain API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# 服务初始化（同步，线程安全）
# ============================================================

_pipeline: IngestionPipeline | None = None
_vector_store: VectorStore | None = None
_metadata_store: MetadataStore | None = None
_hybrid_searcher: HybridSearcher | None = None  # Phase 5F 混合检索器
_checkpointer = None  # LangGraph SqliteSaver——HIL 中断恢复用
_watcher = None  # FileWatcher——文件监听（可经 API 启停）
_scheduler = None  # TaskScheduler——定时任务调度


def _init():
    global _pipeline, _vector_store, _metadata_store, _hybrid_searcher, _checkpointer, _scheduler
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
# 请求/响应模型
# ============================================================


class NoteAddRequest(BaseModel):
    text: str = Field(..., min_length=1, description="笔记内容")
    title: str | None = Field(None, description="标题")


class NoteResponse(BaseModel):
    note_id: str
    message: str


class NoteEditRequest(BaseModel):
    """笔记编辑请求（Phase 4B FR36）。"""
    title: str | None = Field(None, description="新标题")
    add_tags: list[str] = Field(default_factory=list, description="要添加的标签名")
    remove_tags: list[str] = Field(default_factory=list, description="要移除的标签名")


class BookmarkImportResponse(BaseModel):
    """书签导入响应（Phase 4B FR34）。"""
    total: int
    success: int
    skipped: int
    failed: int


class SearchResultItem(BaseModel):
    rank: int
    score: float
    title: str
    content_preview: str
    note_id: str
    tags: list[str]


class SearchResponse(BaseModel):
    query: str
    total: int
    results: list[SearchResultItem]


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1)
    session_id: str | None = Field(None, description="会话 ID（不传则自动创建新会话）")


class AskResponse(BaseModel):
    question: str
    answer: str


class StatusResponse(BaseModel):
    note_count: int
    chunk_count: int
    tag_count: int
    connection_count: int
    top_tags: list[dict]
    recent_notes: list[dict]
    connections: list[dict]


class ConnectionItem(BaseModel):
    source_title: str
    target_title: str
    relation_type: str
    description: str | None
    strength: float


class DigestResponse(BaseModel):
    content: str


class SessionCreateRequest(BaseModel):
    title: str | None = None


class SessionItem(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str


class MessageItem(BaseModel):
    id: int
    role: str
    content: str
    timeline: list = []
    created_at: str


class SessionMessagesResponse(BaseModel):
    session_id: str
    title: str
    messages: list[MessageItem]


# ============================================================
# API 端点
# ============================================================


@app.post("/api/notes", response_model=NoteResponse)
def add_note(req: NoteAddRequest):
    """快速添加笔记。"""
    _init()
    note_id = _pipeline.ingest_text_sync(req.text, title=req.title)
    return NoteResponse(note_id=note_id, message="摄入成功")


@app.get("/api/notes/{note_id}/content")
def get_note_content(note_id: str):
    """精确取回笔记完整正文（复习卡片展开用）。"""
    _init()
    note = _metadata_store.get_note(note_id)
    if note is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="笔记不存在")

    chunks = _vector_store.get_note_chunks(note_id)
    content = "".join(c.content for c in chunks)
    return {
        "note_id": note_id,
        "title": note.title,
        "content": content,
        "ingested_at": note.ingested_at,
    }


@app.post("/api/ingest", response_model=NoteResponse)
def ingest_files(file: UploadFile = File(...)):
    """上传 Markdown 文件摄入。"""
    if not file.filename or not file.filename.endswith(".md"):
        return NoteResponse(note_id="", message="仅支持 .md 文件")

    _init()
    content = file.file.read()
    tmp_path = Path(tempfile.gettempdir()) / f"brain_upload_{uuid.uuid4().hex[:8]}.md"
    tmp_path.write_bytes(content)

    try:
        note_id = _pipeline.ingest_file_sync(tmp_path)
        return NoteResponse(note_id=note_id, message=f"已摄入: {file.filename}")
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


@app.get("/api/search", response_model=SearchResponse)
def search_notes(
    query: str = Query(..., min_length=1),
    tag: str | None = Query(None),
    top_k: int = Query(5, ge=1, le=20),
):
    """语义搜索 + 标签过滤。"""
    _init()

    tag_note_ids: set | None = None
    if tag:
        all_notes = _metadata_store.list_notes(limit=10000)
        tag_note_ids = set()
        for note in all_notes:
            note_tags = _metadata_store.get_note_tags(note.id)
            if any(tag.lower() in t.name.lower() for t in note_tags):
                tag_note_ids.add(note.id)

    results = _vector_store.search(query, top_k=max(top_k * 2, 20))

    items = []
    seen = set()
    for r in results:
        if tag_note_ids is not None and r.note_id not in tag_note_ids:
            continue
        if r.note_id in seen:
            continue
        seen.add(r.note_id)
        if len(items) >= top_k:
            break

        note_tags = _metadata_store.get_note_tags(r.note_id)
        tag_names = [t.name for t in note_tags]

        items.append(SearchResultItem(
            rank=len(items) + 1,
            score=round(r.score, 4),
            title=r.note_title,
            content_preview=r.content[:300],
            note_id=r.note_id,
            tags=tag_names,
        ))

    return SearchResponse(query=query, total=len(items), results=items)


@app.post("/api/ask", response_model=AskResponse)
def ask_question(req: AskRequest):
    """DeepAgents 深度问答（非流式）。"""
    from brain.observability import MetricsTimer, check_budget, new_trace_id, record_metric

    _init()

    # 预算熔断检查（Phase 5B FR48）
    budget = check_budget(_metadata_store)
    if not budget["ok"]:
        from fastapi import HTTPException
        raise HTTPException(status_code=429, detail=budget)

    # 生成 trace_id 贯穿本次问答（Phase 5A）
    trace_id = new_trace_id()
    agent = ResearcherAgent(_vector_store, _metadata_store, hybrid_searcher=_hybrid_searcher)
    with MetricsTimer(
        _metadata_store, "ask", "latency_ms",
        {"question": req.question[:50]}, trace_id=trace_id,
    ):
        answer = agent.research_sync(req.question, trace_id=trace_id)
    # 记录问答计数（与 latency 分开，便于独立统计问答次数）
    record_metric(_metadata_store, "ask", "count", 1, {"question": req.question[:50]}, trace_id=trace_id)
    return AskResponse(question=req.question, answer=answer)


@app.post("/api/ask/stream")
def ask_question_stream(req: AskRequest):
    """DeepAgents 深度问答（SSE 流式，自动持久化到会话）。

    事件格式:
      data: {"type": "session", "session_id": "..."}      # 会话 ID（首次创建时）
      data: {"type": "status", "message": "..."}          # 状态提示
      data: {"type": "tool_start", "name": "...", "args": {...}}  # 工具调用开始
      data: {"type": "tool_end", "name": "..."}           # 工具调用完成
      data: {"type": "token", "content": "..."}           # 答案 token
      data: {"type": "done", "content": ""}               # 完成
    """
    session_id = req.session_id
    import json
    import uuid

    from fastapi.responses import StreamingResponse

    _init()

    # 预算熔断检查（Phase 5B FR48）
    from brain.observability import check_budget
    budget = check_budget(_metadata_store)
    if not budget["ok"]:
        from fastapi import HTTPException
        raise HTTPException(status_code=429, detail=budget)

    # 生成 trace_id 贯穿本次问答（Phase 5A 可观测性）
    from brain.observability import new_trace_id
    trace_id = new_trace_id()  # noqa: F841 在 event_stream 闭包中使用

    agent = ResearcherAgent(_vector_store, _metadata_store, hybrid_searcher=_hybrid_searcher)

    # 会话处理：未指定则自动创建
    created_new_session = False
    if not session_id:
        session_id = uuid.uuid4().hex[:12]
        created_new_session = True
    elif _metadata_store.get_session(session_id) is None:
        # 前端传来的会话不存在（可能被删），重建
        created_new_session = True

    if created_new_session:
        # 用问题前 30 字作为会话标题
        title = req.question[:30] + ("..." if len(req.question) > 30 else "")
        _metadata_store.create_session(session_id, title=title)

    # 先取历史消息（不含刚保存的当前问题），组装多轮上下文
    history = _metadata_store.get_messages(session_id)

    # 第二层记忆：检索跨会话的相关历史消息
    memory_hits = _vector_store.search_memory(
        req.question,
        top_k=5,
        current_session=session_id,  # 同会话旧消息加权（FR27）
    )

    # 保存用户消息（同时写入记忆向量）
    user_msg_id = _metadata_store.add_message(session_id, "user", req.question)
    _vector_store.add_memory(user_msg_id, session_id, "user", req.question)
    _metadata_store.touch_session(session_id)

    def event_stream():
        # 收集回答内容和工具轨迹，流结束后落库
        import time as _time

        from brain.observability import record_metric

        answer_parts: list[str] = []
        timeline: list[dict] = []
        _t0 = _time.perf_counter()

        yield f"data: {json.dumps({'type': 'session', 'session_id': session_id, 'trace_id': trace_id}, ensure_ascii=False)}\n\n"

        try:
            for event in agent.research_stream(
                req.question, session_id, history, memory_hits,
                checkpointer=_checkpointer, trace_id=trace_id,
            ):
                if event["type"] == "token":
                    answer_parts.append(event["content"])
                elif event["type"] == "interrupt":
                    # HIL 中断：保存已流出的答案，向用户请求决策
                    answer = "".join(answer_parts)
                    if answer:
                        _metadata_store.add_message(session_id, "assistant", answer, timeline=timeline)
                        _metadata_store.touch_session(session_id)
                    # 提取全部提议的知识片段（LangGraph 可能一次提议多个，需逐一审批）
                    request = event.get("request") or {}
                    action_requests = request.get("action_requests", [])
                    proposals = [
                        {
                            "name": ar.get("name", ""),
                            "args": ar.get("args", {}),
                            "description": ar.get("description", ""),
                        }
                        for ar in action_requests
                    ]
                    yield f"data: {json.dumps({'type': 'interrupt', 'session_id': session_id, 'proposals': proposals}, ensure_ascii=False)}\n\n"
                    return  # 流结束，等待 /api/ask/resume 恢复
                elif event["type"] == "tool_start" and event.get("name"):
                    timeline.append(
                        {"kind": "tool", "name": event["name"], "args": event.get("args", {}), "done": False}
                    )
                    # 记录工具调用指标（Phase 5A）
                    record_metric(
                        _metadata_store, "tool_call", "count", 1,
                        {"tool_name": event["name"], "args": str(event.get("args", {}))[:200]},
                        trace_id=trace_id,
                    )
                elif event["type"] == "tool_end" and event.get("name"):
                    # 从后往前标记同名工具完成
                    for item in reversed(timeline):
                        if item["kind"] == "tool" and item["name"] == event["name"] and not item["done"]:
                            item["done"] = True
                            break
                elif event["type"] == "done":
                    # 保存 assistant 消息（同时写入记忆向量）
                    answer = "".join(answer_parts)
                    if answer:
                        assistant_msg_id = _metadata_store.add_message(
                            session_id, "assistant", answer, timeline=timeline
                        )
                        _vector_store.add_memory(
                            assistant_msg_id, session_id, "assistant", answer
                        )
                        _metadata_store.touch_session(session_id)
                    # 记录问答 latency 和计数（Phase 5A）
                    elapsed_ms = round((_time.perf_counter() - _t0) * 1000, 1)
                    record_metric(_metadata_store, "ask", "latency_ms", elapsed_ms,
                                  {"question": req.question[:50], "status": "done"},
                                  trace_id=trace_id)
                    record_metric(_metadata_store, "ask", "count", 1,
                                  {"question": req.question[:50]},
                                  trace_id=trace_id)

                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as e:
            # 问答异常：自动收集 bad case（Phase 5D FR54）
            from brain.eval.collector import collect_bad_case
            reason = "recursion_limit" if "recursion" in str(e).lower() else "error"
            collect_bad_case(
                _metadata_store,
                trace_id=trace_id, question=req.question,
                answer="".join(answer_parts), reason=reason,
                extra={"error": str(e)[:200]},
            )
            yield f"data: {json.dumps({'type': 'error', 'message': f'问答失败: {e}'}, ensure_ascii=False)}\n\n"

        # 流正常结束时清理 trace_id 上下文
        # （trace_id 为闭包变量，随生成器回收自动消失，无需 reset）

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


class ResumeRequest(BaseModel):
    session_id: str = Field(..., description="会话 ID（thread_id）")
    decisions: list[dict] = Field(
        ...,
        description='HIL 决策列表，如 [{"type": "approve"}] 或 [{"type": "reject", "message": "..."}]',
    )


@app.post("/api/ask/resume")
def ask_question_resume(req: ResumeRequest):
    """HIL 决策后恢复 Agent 执行（SSE 流式）。

    决策格式:
      approve: {"type": "approve"}                       → 原样执行工具
      edit:    {"type": "edit", "edited_action": {"name": ..., "args": {...}}}
      reject:  {"type": "reject", "message": "..."}      → 跳过工具
    """
    import json

    from fastapi.responses import StreamingResponse

    _init()

    agent = ResearcherAgent(_vector_store, _metadata_store, hybrid_searcher=_hybrid_searcher)

    # HIL 恢复也生成新 trace_id（Phase 5A）
    from brain.observability import new_trace_id
    resume_trace_id = new_trace_id()

    def resume_stream():
        import time as _time

        from brain.observability import record_metric

        answer_parts: list[str] = []
        timeline: list[dict] = []
        _t0 = _time.perf_counter()

        for event in agent.resume_stream(
            req.session_id,
            {"decisions": req.decisions},
            checkpointer=_checkpointer,
            trace_id=resume_trace_id,
        ):
            if event["type"] == "token":
                answer_parts.append(event["content"])
            elif event["type"] == "tool_start" and event.get("name"):
                timeline.append(
                    {"kind": "tool", "name": event["name"], "args": event.get("args", {}), "done": False}
                )
                record_metric(
                    _metadata_store, "tool_call", "count", 1,
                    {"tool_name": event["name"], "args": str(event.get("args", {}))[:200]},
                    trace_id=resume_trace_id,
                )
            elif event["type"] == "tool_end" and event.get("name"):
                for item in reversed(timeline):
                    if item["kind"] == "tool" and item["name"] == event["name"] and not item["done"]:
                        item["done"] = True
                        break
            elif event["type"] == "done":
                answer = "".join(answer_parts)
                if answer:
                    assistant_msg_id = _metadata_store.add_message(
                        req.session_id, "assistant", answer, timeline=timeline
                    )
                    _vector_store.add_memory(
                        assistant_msg_id, req.session_id, "assistant", answer
                    )
                    _metadata_store.touch_session(req.session_id)
                elapsed_ms = round((_time.perf_counter() - _t0) * 1000, 1)
                record_metric(_metadata_store, "ask", "latency_ms", elapsed_ms,
                              {"session_id": req.session_id, "status": "resumed"},
                              trace_id=resume_trace_id)

            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        # （resume_trace_id 为闭包变量，随生成器回收自动消失，无需 reset）

    return StreamingResponse(
        resume_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ============================================================
# 会话管理 API
# ============================================================


@app.post("/api/sessions", response_model=SessionItem)
def create_session(req: SessionCreateRequest):
    """创建新会话。"""
    import uuid

    _init()
    session_id = uuid.uuid4().hex[:12]
    title = req.title or "新对话"
    _metadata_store.create_session(session_id, title=title)
    session = _metadata_store.get_session(session_id)
    return SessionItem(**session)


@app.get("/api/sessions", response_model=list[SessionItem])
def list_sessions():
    """列出全部会话。"""
    _init()
    sessions = _metadata_store.list_sessions()
    return [SessionItem(**s) for s in sessions]


@app.get("/api/sessions/{session_id}/messages", response_model=SessionMessagesResponse)
def get_session_messages(session_id: str):
    """获取会话的消息历史。"""
    _init()
    session = _metadata_store.get_session(session_id)
    if session is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="会话不存在")

    messages = _metadata_store.get_messages(session_id)
    return SessionMessagesResponse(
        session_id=session_id,
        title=session["title"],
        messages=[MessageItem(**m) for m in messages],
    )


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str):
    """删除会话（含全部消息和记忆向量）。"""
    _init()
    _metadata_store.delete_session(session_id)
    _vector_store.delete_session_memory(session_id)
    return {"ok": True}


@app.get("/api/fragments")
def list_fragments(limit: int = Query(50, ge=1, le=200)):
    """列出已保存的知识片段（HIL 确认后的沉淀内容）。"""
    _init()
    fragments = _metadata_store.list_knowledge_fragments(limit=limit)
    return fragments


@app.delete("/api/fragments/{fragment_id}")
def delete_fragment(fragment_id: int):
    """删除知识片段（SQLite + 向量同步删除）。"""
    _init()
    ok = _metadata_store.delete_knowledge_fragment(fragment_id)
    if not ok:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="片段不存在")
    _vector_store.delete_fragment(fragment_id)
    return {"ok": True}


# ============================================================
# 文件监听 API
# ============================================================


class WatchStatusResponse(BaseModel):
    running: bool
    watch_dir: str
    recent_events: list[dict]


@app.get("/api/watch", response_model=WatchStatusResponse)
def watch_status():
    """查询文件监听状态。"""
    _init()
    global _watcher

    cfg = get_config()
    if _watcher is not None and _watcher.is_running():
        return WatchStatusResponse(
            running=True,
            watch_dir=str(_watcher.watch_dir),
            recent_events=_watcher.get_recent_events(),
        )
    return WatchStatusResponse(
        running=False,
        watch_dir=str(cfg.storage.notes_dir),
        recent_events=[],
    )


@app.post("/api/watch/start", response_model=WatchStatusResponse)
def watch_start():
    """启动文件监听（后台线程）。"""
    _init()
    global _watcher

    from brain.ingestion.watcher import FileWatcher

    if _watcher is not None and _watcher.is_running():
        return WatchStatusResponse(
            running=True,
            watch_dir=str(_watcher.watch_dir),
            recent_events=_watcher.get_recent_events(),
        )

    cfg = get_config()
    watch_dir = cfg.storage.notes_dir
    watch_dir.mkdir(parents=True, exist_ok=True)

    def _on_file(file_path):
        try:
            note_id = _pipeline.ingest_file_sync(file_path)
            _watcher.record_event(file_path.name, note_id)
            logger.info(f"[watch] ✅ {file_path.name} → {note_id}")
        except Exception as e:
            logger.warning(f"[watch] ❌ {file_path.name}: {e}")

    _watcher = FileWatcher(
        watch_dir=watch_dir,
        ingest_callback=_on_file,
        debounce_seconds=cfg.ingestion.debounce_seconds,
    )
    _watcher.start()

    return WatchStatusResponse(
        running=True,
        watch_dir=str(watch_dir),
        recent_events=[],
    )


@app.post("/api/watch/stop", response_model=WatchStatusResponse)
def watch_stop():
    """停止文件监听。"""
    _init()
    global _watcher

    if _watcher is not None:
        _watcher.stop()
        _watcher = None

    cfg = get_config()
    return WatchStatusResponse(
        running=False,
        watch_dir=str(cfg.storage.notes_dir),
        recent_events=[],
    )


# ============================================================
# RSS 订阅 API
# ============================================================


class RssAddRequest(BaseModel):
    url: str = Field(..., min_length=1, description="RSS/Atom 订阅源 URL")


class RssFetchResponse(BaseModel):
    feeds_checked: int
    new_entries: int
    errors: list[str]


@app.get("/api/rss")
def rss_list():
    """列出全部 RSS 订阅源。"""
    _init()
    return _metadata_store.list_rss_feeds()


@app.post("/api/rss", response_model=RssFetchResponse)
def rss_add_and_fetch(req: RssAddRequest):
    """添加订阅源并立即拉取一次。"""
    _init()

    from brain.ingestion.sources.rss import RssSource

    source = RssSource(_pipeline, _metadata_store)
    feed_id = source.add_feed(req.url)
    new_count = source.fetch_feed(feed_id)

    return RssFetchResponse(
        feeds_checked=1,
        new_entries=new_count,
        errors=[],
    )


@app.post("/api/rss/fetch", response_model=RssFetchResponse)
def rss_fetch_all():
    """拉取所有订阅源的新文章。"""
    _init()

    from brain.ingestion.sources.rss import RssSource

    source = RssSource(_pipeline, _metadata_store)
    summary = source.fetch_all()
    return RssFetchResponse(**summary)


@app.delete("/api/rss/{feed_id}")
def rss_delete(feed_id: int):
    """删除 RSS 订阅源。"""
    _init()
    ok = _metadata_store.delete_rss_feed(feed_id)
    if not ok:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="订阅源不存在")
    return {"ok": True}


# ============================================================
# 定时任务调度 API
# ============================================================


@app.get("/api/scheduler")
def scheduler_status():
    """查询定时任务状态。"""
    _init()
    if _scheduler is None:
        return []
    return _scheduler.get_status()


@app.post("/api/scheduler/run/{task_name}")
def scheduler_run_now(task_name: str):
    """手动立即执行某定时任务。

    task_name: rss_sync | daily_digest | weekly_digest
    """
    _init()
    if _scheduler is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=503, detail="调度器未初始化")

    result = _scheduler.run_now(task_name)
    if result is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=f"任务不存在: {task_name}")
    return {"task": task_name, "result": result}


@app.get("/api/digest/reports")
def digest_reports(limit: int = Query(10, ge=1, le=50)):
    """列出最近生成的摘要报告（定时任务产物）。"""
    _init()
    return _metadata_store.list_digest_reports(limit=limit)


@app.get("/api/graph")
def knowledge_graph():
    """知识图谱数据——笔记节点 + 关联边。

    全部走批量 SQL（一次取关联、一次取度数、一次取标签），
    无 N+1 查询，500+ 笔记时依然毫秒级响应。
    """
    _init()

    # 一次 SQL：全部关联 + 两端标题
    flat_conns = _metadata_store.get_all_connections_flat()

    edges = [
        {
            "source": c["source"],
            "target": c["target"],
            "relation_type": c["relation_type"],
            "strength": c["strength"],
            "description": c["description"],
        }
        for c in flat_conns
    ]

    # 一次 SQL：度数统计
    degree_map = _metadata_store.get_note_degree_map()

    # 一次 SQL：全部笔记 + 批量标签
    all_notes = _metadata_store.list_notes(limit=10000)
    tags_map = _metadata_store.get_tags_batch([n.id for n in all_notes])

    nodes = [
        {
            "id": note.id,
            "title": note.title[:30],
            "tags": [t.name for t in tags_map.get(note.id, [])][:3],
            "degree": degree_map.get(note.id, 0),
            "date": note.ingested_at[:10] if note.ingested_at else "",
        }
        for note in all_notes
    ]

    return {"nodes": nodes, "edges": edges}


# ============================================================
# 可观测性 API（Phase 5A）
# ============================================================


@app.get("/api/health")
def get_health():
    """健康检查——探测 LLM/Embedding/SQLite/ChromaDB 连通性。

    LLM 探测默认跳过（避免烧配额），仅 dry_run 时真调。
    Embedding 探测用空字符串，不消耗有意义配额。
    """
    from brain.observability import check_health

    _init()
    # embedding_fn 懒加载传入（避免在 health 检查外初始化）
    try:
        embedding_fn = get_embedding_fn()
    except Exception:
        embedding_fn = None
    return check_health(_metadata_store, _vector_store, embedding_fn)


@app.get("/api/metrics/summary")
def get_metrics_summary(hours: int = Query(24, ge=1, le=168, description="统计时间窗口（小时）")):
    """指标汇总（看板用）。"""
    _init()
    return _metadata_store.get_metrics_summary(hours=hours)


@app.get("/api/metrics/traces")
def get_recent_traces(limit: int = Query(20, ge=1, le=100)):
    """最近问答调用链列表。"""
    _init()
    return _metadata_store.get_recent_traces(limit=limit)


# ============================================================
# 成本治理 API（Phase 5B FR49）
# ============================================================


@app.get("/api/cost/summary")
def get_cost_summary():
    """成本汇总（今日/本月/总累计 + 配额用量）。"""
    _init()
    from brain.observability import check_budget

    summary = _metadata_store.get_cost_summary()
    budget = check_budget(_metadata_store)
    return {**summary, "budget": budget}


@app.get("/api/cost/by-model")
def get_cost_by_model(hours: int = Query(24, ge=1, le=720)):
    """按模型聚合成本。"""
    _init()
    return _metadata_store.get_cost_by_model(hours=hours)


@app.get("/api/cost/by-day")
def get_cost_by_day(days: int = Query(30, ge=1, le=365)):
    """按日聚合成本趋势。"""
    _init()
    return _metadata_store.get_cost_by_day(days=days)


# ============================================================
# 评估反馈 API（Phase 5D FR54）
# ============================================================


class EvalFeedbackRequest(BaseModel):
    trace_id: str | None = Field(None, description="问答的 trace_id（便于回溯）")
    question: str = Field(..., description="用户问题")
    answer: str = Field(..., description="Agent 回答")
    reason: str = Field("user_thumbs_down", description="点踩原因")


@app.post("/api/eval/feedback")
def submit_eval_feedback(req: EvalFeedbackRequest):
    """用户点踩 bad case → 收集到数据库。"""
    from brain.eval.collector import collect_bad_case

    _init()
    collect_bad_case(
        _metadata_store,
        trace_id=req.trace_id,
        question=req.question,
        answer=req.answer,
        reason=req.reason,
    )
    return {"message": "已收集，感谢反馈"}


@app.get("/api/eval/scores")
def get_eval_scores(limit: int = Query(50, ge=1, le=200)):
    """获取最近的 LLM-as-Judge 打分。"""
    _init()
    return _metadata_store.get_eval_scores(limit=limit)


@app.get("/api/eval/scores/summary")
def get_eval_score_summary():
    """评估打分汇总（平均分/分布）。"""
    _init()
    return _metadata_store.get_eval_score_summary()


@app.get("/api/eval/bad-cases")
def get_bad_cases():
    """查看已收集的 bad cases。"""
    _init()
    return _metadata_store.get_bad_cases()


@app.delete("/api/eval/bad-cases/{case_id}")
def delete_bad_case(case_id: int):
    """删除一条 bad case。"""
    from fastapi import HTTPException

    _init()
    if _metadata_store.delete_bad_case(case_id):
        return {"message": "已删除"}
    raise HTTPException(status_code=404, detail="bad case 不存在")


@app.post("/api/eval/bad-cases/{case_id}/to-golden")
def bad_case_to_golden(case_id: int, min_score: float = Query(0.7, ge=0, le=1.0)):
    """将 bad case 转为 golden case（需人工补充关键词后可启用）。"""
    from fastapi import HTTPException

    _init()
    cases = _metadata_store.get_bad_cases(limit=1000)
    target = next((c for c in cases if c["id"] == case_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="bad case 不存在")

    # 生成 case_id：bc_<id>
    new_id = f"bc_{case_id}"
    _metadata_store.add_golden_case(
        case_id=new_id,
        question=target["question"],
        expected_keywords=[],  # 待人工补充
        expected_sources=[],
        min_score=min_score,
        enabled=False,  # 默认禁用，补充关键词后手动启用
    )
    return {"message": f"已转为 golden case（id={new_id}），请补充关键词后启用", "golden_id": new_id}


# ---- Golden Cases CRUD（Phase 5D FR53） ----


@app.get("/api/eval/golden-cases")
def get_golden_cases(enabled_only: bool = Query(False)):
    """获取 golden cases 列表。"""
    _init()
    return _metadata_store.get_golden_cases(enabled_only=enabled_only)


class GoldenCaseRequest(BaseModel):
    id: str = Field(..., description="用例 ID，如 eval_001")
    question: str = Field(..., description="问题")
    expected_keywords: list[str] = Field(default_factory=list, description="期望关键词")
    expected_sources: list[str] = Field(default_factory=list, description="期望引用笔记 id")
    min_score: float = Field(0.7, ge=0, le=1.0, description="及格分")
    enabled: bool = Field(True, description="是否启用")


@app.post("/api/eval/golden-cases")
def create_golden_case(req: GoldenCaseRequest):
    """新增/更新 golden case（id 相同则覆盖）。"""
    _init()
    _metadata_store.add_golden_case(
        case_id=req.id,
        question=req.question,
        expected_keywords=req.expected_keywords,
        expected_sources=req.expected_sources,
        min_score=req.min_score,
        enabled=req.enabled,
    )
    return {"message": "已保存", "id": req.id}


@app.patch("/api/eval/golden-cases/{case_id}")
def update_golden_case(case_id: str, req: GoldenCaseRequest):
    """更新 golden case。"""
    _init()
    _metadata_store.update_golden_case(
        case_id,
        question=req.question,
        expected_keywords=req.expected_keywords,
        expected_sources=req.expected_sources,
        min_score=req.min_score,
        enabled=req.enabled,
    )
    return {"message": "已更新"}


@app.delete("/api/eval/golden-cases/{case_id}")
def delete_golden_case(case_id: str):
    """删除 golden case。"""
    from fastapi import HTTPException

    _init()
    if _metadata_store.delete_golden_case(case_id):
        return {"message": "已删除"}
    raise HTTPException(status_code=404, detail="golden case 不存在")


@app.post("/api/eval/golden-cases/{case_id}/toggle")
def toggle_golden_case(case_id: str):
    """启用/禁用 golden case。"""
    from fastapi import HTTPException

    _init()
    cases = _metadata_store.get_golden_cases()
    target = next((c for c in cases if c["id"] == case_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="golden case 不存在")
    _metadata_store.update_golden_case(case_id, enabled=not target["enabled"])
    return {"message": "已切换", "enabled": not target["enabled"]}


@app.post("/api/eval/seed")
def seed_golden_cases():
    """从 YAML 种子文件导入 golden cases 到数据库。"""
    _init()
    from brain.eval.runner import seed_golden_dataset

    count = seed_golden_dataset(_metadata_store)
    return {"message": f"已导入 {count} 条", "count": count}


@app.get("/api/eval/runs")
def get_eval_runs(
    limit: int = Query(20, ge=1, le=100),
    run_type: str | None = Query(None, description="offline | judge，空=全部"),
):
    """获取评估批次历史（Phase 5D）。"""
    _init()
    return _metadata_store.get_eval_runs(limit=limit, run_type=run_type)


@app.post("/api/eval/judge")
def run_judge_sample(sample_rate: float = Query(0.1, ge=0.01, le=1.0), limit: int = Query(10, ge=1, le=50)):
    """手动触发 LLM-as-Judge 抽样打分（Phase 5D FR55）。"""
    _init()
    from brain.eval.judge import LLMJudge

    judge = LLMJudge(_metadata_store)
    results = judge.judge_recent_traces(sample_rate=sample_rate, limit=limit)
    return {"judged": len(results), "results": results}


@app.post("/api/eval/run")
def run_eval_dataset(limit: int = Query(0, ge=0, le=50, description="只跑前 N 条，0=全部")):
    """手动触发离线评估测试集（Phase 5D FR53）。

    跑 Golden Dataset，返回打分报告。注意：会真实调用 LLM，消耗 token。
    """
    _init()
    from brain.eval.runner import EvalRunner

    runner = EvalRunner(_vector_store, _metadata_store)
    actual_limit = limit if limit > 0 else None
    report = runner.run(limit=actual_limit)  # None=从数据库加载

    # 持久化评估批次到 eval_runs（Phase 5D）——存完整结果供历史查看
    all_results = [
        {
            "id": r.case.id,
            "question": r.case.question[:60],
            "answer": r.answer[:200],
            "score": r.score,
            "passed": r.passed,
            "min_score": r.case.min_score,
            "details": r.details,
            "trace_id": r.trace_id,
            "error": r.error,
        }
        for r in report.results
    ]
    _metadata_store.add_eval_run(
        run_type="offline",
        total=report.total,
        passed=report.passed,
        pass_rate=round(report.pass_rate, 4),
        avg_score=round(report.avg_score, 4),
        duration_ms=round(report.duration_ms, 0),
        details={"results": all_results},
    )

    # 序列化报告（dataclass → dict）
    return {
        "total": report.total,
        "passed": report.passed,
        "failed": report.failed,
        "pass_rate": round(report.pass_rate, 4),
        "avg_score": round(report.avg_score, 4),
        "duration_ms": round(report.duration_ms, 0),
        "started_at": report.started_at,
        "results": [
            {
                "id": r.case.id,
                "question": r.case.question,
                "answer": r.answer,
                "score": r.score,
                "passed": r.passed,
                "min_score": r.case.min_score,
                "details": r.details,
                "trace_id": r.trace_id,
                "error": r.error,
            }
            for r in report.results
        ],
    }


# ---- Prompts CRUD（Phase 5E FR56） ----


@app.get("/api/prompts")
def list_prompts():
    """列出全部提示词（不含正文，列表展示用）。"""
    _init()
    return _metadata_store.list_prompts()


@app.get("/api/prompts/{prompt_key}")
def get_prompt_detail(prompt_key: str):
    """获取单条提示词详情（含正文）。"""
    from fastapi import HTTPException

    _init()
    row = _metadata_store.get_prompt(prompt_key)
    if not row:
        raise HTTPException(status_code=404, detail="提示词不存在")
    return row


class PromptUpdateRequest(BaseModel):
    content: str = Field(..., description="提示词正文")
    enabled: bool | None = Field(None, description="是否启用（不传则不变）")


@app.put("/api/prompts/{prompt_key}")
def update_prompt(prompt_key: str, req: PromptUpdateRequest):
    """更新提示词内容（version 自增），并刷新缓存即时生效。"""
    from fastapi import HTTPException

    _init()
    if not _metadata_store.update_prompt(prompt_key, req.content, req.enabled):
        raise HTTPException(status_code=404, detail="提示词不存在")
    # 刷新缓存，下次 Agent 调用即用新提示词
    from brain.prompts import reload_prompt

    reload_prompt(prompt_key)
    return {"message": "已更新", "prompt_key": prompt_key}


@app.get("/api/prompts/{prompt_key}/versions")
def list_prompt_versions(prompt_key: str):
    """列出某提示词的历史版本（按版本号降序）。"""
    _init()
    return _metadata_store.list_prompt_versions(prompt_key)


@app.get("/api/prompts/{prompt_key}/versions/{version}")
def get_prompt_version(prompt_key: str, version: int):
    """获取某历史版本的正文。"""
    from fastapi import HTTPException

    _init()
    row = _metadata_store.get_prompt_version(prompt_key, version)
    if not row:
        raise HTTPException(status_code=404, detail="历史版本不存在")
    return row


@app.post("/api/prompts/{prompt_key}/versions/{version}/restore")
def restore_prompt_version(prompt_key: str, version: int):
    """恢复某历史版本为最新（该版本内容设为当前，version 继续自增）。"""
    from fastapi import HTTPException

    _init()
    if not _metadata_store.restore_prompt_version(prompt_key, version):
        raise HTTPException(status_code=404, detail="历史版本不存在")
    from brain.prompts import reload_prompt

    reload_prompt(prompt_key)
    return {"message": f"已恢复 v{version}", "prompt_key": prompt_key}


@app.get("/api/metrics/traces/{trace_id}")
def get_trace_detail(trace_id: str):
    """某条 trace 的完整调用链。

    返回两个部分：
      - events: trace_events 表的完整调用日志（LLM 请求响应、工具入参出参）
      - metrics: metrics 表的数值指标（latency/token/count）
    """
    _init()
    return {
        "events": _metadata_store.get_trace_events(trace_id),
        "metrics": _metadata_store.get_trace_detail(trace_id),
    }


@app.get("/api/status", response_model=StatusResponse)
def get_status():
    """知识库统计概览。

    全部走批量 SQL（一次标签统计、一次关联、一次批量标签），
    无 N+1 查询。
    """
    _init()

    chunk_count = _vector_store.count()
    note_count = _metadata_store.count_notes()

    # 一次 SQL：标签统计
    tag_counts = _metadata_store.get_tag_counts()

    # 一次 SQL：全部关联（含标题）
    flat_conns = _metadata_store.get_all_connections_flat()
    total_conns = len(flat_conns)
    all_conns = [
        {
            "source_title": c["source_title"],
            "target_title": c["target_title"],
            "relation_type": c["relation_type"],
            "description": c["description"],
            "strength": c["strength"],
        }
        for c in flat_conns
    ]

    top_tags = [
        {"name": name, "count": count}
        for name, count in sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    ]

    # 一次 SQL：最近笔记 + 批量标签
    recent = _metadata_store.list_notes(limit=5)
    tags_map = _metadata_store.get_tags_batch([n.id for n in recent])
    recent_notes = [
        {
            "note_id": note.id,
            "title": note.title,
            "date": note.ingested_at[:10] if note.ingested_at else "?",
            "tags": [t.name for t in tags_map.get(note.id, [])],
        }
        for note in recent
    ]

    return StatusResponse(
        note_count=note_count, chunk_count=chunk_count,
        tag_count=len(tag_counts), connection_count=total_conns,
        top_tags=top_tags, recent_notes=recent_notes, connections=all_conns,
    )


@app.get("/api/connections", response_model=list[ConnectionItem])
def get_connections():
    """获取所有关联（一次 SQL JOIN 查询）。"""
    _init()

    flat_conns = _metadata_store.get_all_connections_flat()
    return [
        ConnectionItem(
            source_title=c["source_title"],
            target_title=c["target_title"],
            relation_type=c["relation_type"],
            description=c["description"],
            strength=c["strength"],
        )
        for c in flat_conns
    ]


# ---- Phase 4B：标签浏览 / 笔记编辑 / 书签导入 / 关联删除 ----

@app.get("/api/tags")
def list_tags():
    """列出全部标签及使用计数（FR35）。"""
    _init()
    return _metadata_store.list_all_tags()


@app.patch("/api/notes/{note_id}")
def edit_note(note_id: str, req: NoteEditRequest):
    """编辑笔记标题和标签（FR36）。内容编辑请重新摄入。"""
    from fastapi import HTTPException

    from brain.models import TagCategory

    _init()
    note = _metadata_store.get_note(note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="笔记不存在")

    changed = []
    if req.title is not None:
        _metadata_store.update_note(note_id, title=req.title.strip())
        changed.append("title")

    for tag_name in req.add_tags:
        tag_id = _metadata_store.get_or_create_tag(
            name=tag_name.strip(), category=TagCategory.TOPIC, is_ai=False
        )
        _metadata_store.add_tag_to_note(note_id=note_id, tag_id=tag_id, confidence=1.0)
    if req.add_tags:
        changed.append(f"+{len(req.add_tags)}tags")

    for tag_name in req.remove_tags:
        _metadata_store.remove_tag_from_note(note_id, tag_name.strip())
    if req.remove_tags:
        changed.append(f"-{len(req.remove_tags)}tags")

    return {"note_id": note_id, "changed": changed or "none"}


@app.delete("/api/connections/{conn_id}")
def delete_connection(conn_id: int):
    """删除指定 ID 的关联（FR36）。"""
    from fastapi import HTTPException

    _init()
    if not _metadata_store.delete_connection(conn_id):
        raise HTTPException(status_code=404, detail="关联不存在")
    return {"message": "已删除", "conn_id": conn_id}


@app.post("/api/bookmarks/import", response_model=BookmarkImportResponse)
def import_bookmarks(file: UploadFile = File(...)):
    """导入浏览器书签 JSON 文件（FR34）。支持 Chrome/Firefox 格式。"""
    import tempfile
    from pathlib import Path

    from brain.ingestion.sources import BookmarkSource

    _init()
    # 保存上传文件到临时路径
    suffix = Path(file.filename or "bookmarks.json").suffix or ".json"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(file.file.read())
        tmp_path = Path(tmp.name)

    try:
        source = BookmarkSource(_pipeline, _metadata_store)
        summary = source.import_file(tmp_path)
        return BookmarkImportResponse(**summary)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


@app.get("/api/digest", response_model=DigestResponse)
def get_digest(weekly: bool = Query(False)):
    """生成知识摘要。"""
    _init()
    svc = DigestService(_metadata_store)
    result = svc.daily_sync() if not weekly else svc.weekly_sync()
    return DigestResponse(content=result)


@app.get("/api/review")
def get_review(limit: int = Query(10, ge=1, le=50)):
    """SM-2 到期复习列表（含未进入系统的新卡片）。"""
    _init()
    svc = ReviewService(_metadata_store)
    due = svc.get_due_items_sync(limit=limit)
    return {"total": len(due), "items": due}


class ReviewRecordRequest(BaseModel):
    note_id: str = Field(..., description="笔记 ID")
    quality: int = Field(..., ge=0, le=5, description="0-5 评分（0-2忘记/3困难/4良好/5简单）")


@app.post("/api/review/record")
def record_review(req: ReviewRecordRequest):
    """记录复习评分，SM-2 计算下次复习时间。"""
    _init()
    svc = ReviewService(_metadata_store)
    return svc.record_review_sync(req.note_id, req.quality)


# ============================================================
# 前端静态文件
# ============================================================

_frontend_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"

# 挂载静态资源目录（JS/CSS 等），否则 /assets/*.js 返回 404
_assets_dir = _frontend_dist / "assets"
if _assets_dir.exists():
    from fastapi.staticfiles import StaticFiles
    app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="assets")


@app.get("/")
def serve_frontend():
    index_path = _frontend_dist / "index.html"
    if index_path.exists():
        from fastapi.responses import FileResponse
        return FileResponse(index_path)
    return {"message": "前端未构建。运行: cd frontend && npm run build"}


@app.get("/{full_path:path}")
def serve_spa(full_path: str):
    """SPA fallback：所有非 /api 路径返回 index.html（支持前端路由刷新）。"""
    # /assets/* 已由 StaticFiles 处理，不会走到这里
    index_path = _frontend_dist / "index.html"
    if index_path.exists():
        from fastapi.responses import FileResponse
        return FileResponse(index_path)
    return {"message": "前端未构建"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("brain.api.server:app", host="127.0.0.1", port=7860, reload=True)
