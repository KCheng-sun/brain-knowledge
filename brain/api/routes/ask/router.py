"""深度问答业务域 API 路由（含会话管理 + 知识片段）。

端点:
  POST   /api/ask                       — 深度问答（非流式）
  POST   /api/ask/stream                — 深度问答（SSE 流式，HIL 中断）
  POST   /api/ask/resume                — HIL 决策后恢复执行
  POST   /api/sessions                  — 创建会话
  GET    /api/sessions                  — 列出会话
  GET    /api/sessions/{id}/messages    — 会话消息历史
  DELETE /api/sessions/{id}             — 删除会话
  GET    /api/fragments                 — 列出知识片段
  DELETE /api/fragments/{fragment_id}   — 删除知识片段
"""

import json
import uuid

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from brain.agents.researcher import ResearcherAgent
from brain.api.deps import (
    get_checkpointer,
    get_hybrid_searcher,
    get_metadata_store,
    get_vector_store,
)
from brain.api.routes.ask.models import (
    AskRequest,
    AskResponse,
    MessageItem,
    ResumeRequest,
    SessionCreateRequest,
    SessionItem,
    SessionMessagesResponse,
)

router = APIRouter(prefix="/api", tags=["ask"])


@router.post("/ask", response_model=AskResponse)
def ask_question(req: AskRequest):
    """DeepAgents 深度问答（非流式）。"""
    from brain.observability import MetricsTimer, check_budget, new_trace_id, record_metric

    # 预算熔断检查（Phase 5B FR48）
    budget = check_budget(get_metadata_store())
    if not budget["ok"]:
        raise HTTPException(status_code=429, detail=budget)

    # 生成 trace_id 贯穿本次问答（Phase 5A）
    trace_id = new_trace_id()
    ms = get_metadata_store()
    agent = ResearcherAgent(get_vector_store(), ms, hybrid_searcher=get_hybrid_searcher())
    with MetricsTimer(
        ms, "ask", "latency_ms",
        {"question": req.question[:50]}, trace_id=trace_id,
    ):
        answer = agent.research_sync(req.question, trace_id=trace_id)
    # 记录问答计数（与 latency 分开，便于独立统计问答次数）
    record_metric(ms, "ask", "count", 1, {"question": req.question[:50]}, trace_id=trace_id)
    return AskResponse(question=req.question, answer=answer)


@router.post("/ask/stream")
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
    ms = get_metadata_store()
    vs = get_vector_store()
    session_id = req.session_id

    # 预算熔断检查（Phase 5B FR48）
    from brain.observability import check_budget
    budget = check_budget(ms)
    if not budget["ok"]:
        raise HTTPException(status_code=429, detail=budget)

    # 生成 trace_id 贯穿本次问答（Phase 5A 可观测性）
    from brain.observability import new_trace_id
    trace_id = new_trace_id()  # noqa: F841 在 event_stream 闭包中使用

    agent = ResearcherAgent(vs, ms, hybrid_searcher=get_hybrid_searcher())

    # 会话处理：未指定则自动创建
    created_new_session = False
    if not session_id:
        session_id = uuid.uuid4().hex[:12]
        created_new_session = True
    elif ms.get_session(session_id) is None:
        # 前端传来的会话不存在（可能被删），重建
        created_new_session = True

    if created_new_session:
        # 用问题前 30 字作为会话标题
        title = req.question[:30] + ("..." if len(req.question) > 30 else "")
        ms.create_session(session_id, title=title)

    # 先取历史消息（不含刚保存的当前问题），组装多轮上下文
    history = ms.get_messages(session_id)

    # 第二层记忆：检索跨会话的相关历史消息
    memory_hits = vs.search_memory(
        req.question,
        top_k=5,
        current_session=session_id,  # 同会话旧消息加权（FR27）
    )

    # 保存用户消息（同时写入记忆向量）
    user_msg_id = ms.add_message(session_id, "user", req.question)
    vs.add_memory(user_msg_id, session_id, "user", req.question)
    ms.touch_session(session_id)

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
                checkpointer=get_checkpointer(), trace_id=trace_id,
            ):
                if event["type"] == "token":
                    answer_parts.append(event["content"])
                elif event["type"] == "interrupt":
                    # HIL 中断：保存已流出的答案为「待续消息」（status=pending），
                    # msg_id 暂存到 session 表，resume 完成时更新同一条消息（合并内容）
                    answer = "".join(answer_parts)
                    # 中断后不会再收到 tool_end，把未完成 tool 强制标记为 done
                    for item in timeline:
                        if item.get("kind") == "tool" and not item.get("done"):
                            item["done"] = True
                    if answer or timeline:
                        msg_id = ms.add_message(
                            session_id, "assistant", answer, timeline=timeline, status="pending"
                        )
                        ms.set_pending_msg_id(session_id, msg_id)
                        ms.touch_session(session_id)
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
                    # 把工具调用前已流出的文本归档为「思考片段」进 timeline，
                    # 保持与前端一致的交错顺序（文本-工具-文本-工具-...）
                    partial = "".join(answer_parts)
                    if partial.strip():
                        timeline.append({"kind": "thought", "content": partial})
                        answer_parts = []  # 清空，下一段文本重新累积
                    timeline.append(
                        {"kind": "tool", "name": event["name"], "args": event.get("args", {}), "done": False}
                    )
                    # 记录工具调用指标（Phase 5A）
                    record_metric(
                        ms, "tool_call", "count", 1,
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
                    # memory 向量用全文（thought 片段 + 最后一段），保证语义完整
                    full_text = " \n".join(
                        [t["content"] for t in timeline if t.get("kind") == "thought"] + ([answer] if answer else [])
                    )
                    if answer or timeline:
                        assistant_msg_id = ms.add_message(
                            session_id, "assistant", answer, timeline=timeline
                        )
                        if full_text:
                            vs.add_memory(
                                assistant_msg_id, session_id, "assistant", full_text
                            )
                        ms.touch_session(session_id)
                    # 记录问答 latency 和计数（Phase 5A）
                    elapsed_ms = round((_time.perf_counter() - _t0) * 1000, 1)
                    record_metric(ms, "ask", "latency_ms", elapsed_ms,
                                  {"question": req.question[:50], "status": "done"},
                                  trace_id=trace_id)
                    record_metric(ms, "ask", "count", 1,
                                  {"question": req.question[:50]},
                                  trace_id=trace_id)

                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as e:
            # 问答异常：自动收集 bad case（Phase 5D FR54）
            from brain.eval.collector import collect_bad_case
            reason = "recursion_limit" if "recursion" in str(e).lower() else "error"
            collect_bad_case(
                ms,
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


@router.post("/ask/resume")
def ask_question_resume(req: ResumeRequest):
    """HIL 决策后恢复 Agent 执行（SSE 流式）。

    决策格式:
      approve: {"type": "approve"}                       → 原样执行工具
      edit:    {"type": "edit", "edited_action": {"name": ..., "args": {...}}}
      reject:  {"type": "reject", "message": "..."}      → 跳过工具
    """
    ms = get_metadata_store()
    vs = get_vector_store()
    agent = ResearcherAgent(vs, ms, hybrid_searcher=get_hybrid_searcher())

    # HIL 恢复也生成新 trace_id（Phase 5A）
    from brain.observability import new_trace_id
    resume_trace_id = new_trace_id()

    def resume_stream():
        import time as _time

        from brain.observability import record_metric

        answer_parts: list[str] = []
        timeline: list[dict] = []
        _t0 = _time.perf_counter()

        # 取出中断时保存的待续消息（pending），resume 完成后合并更新同一条
        pending_id = ms.get_pending_msg_id(req.session_id)
        prev_content = ""
        prev_timeline: list[dict] = []
        if pending_id is not None:
            for m in ms.get_messages(req.session_id):
                if m["id"] == pending_id:
                    prev_content = m.get("content", "") or ""
                    prev_timeline = m.get("timeline", []) or []
                    break

        for event in agent.resume_stream(
            req.session_id,
            {"decisions": req.decisions},
            checkpointer=get_checkpointer(),
            trace_id=resume_trace_id,
        ):
            if event["type"] == "token":
                answer_parts.append(event["content"])
            elif event["type"] == "interrupt":
                # resume 后再次中断（多片段逐一审批）：合并已流出的内容到待续消息
                answer = "".join(answer_parts)
                for item in timeline:
                    if item.get("kind") == "tool" and not item.get("done"):
                        item["done"] = True
                if pending_id is not None:
                    ms.update_message(
                        pending_id,
                        prev_content + answer,
                        timeline=prev_timeline + timeline,
                        status="pending",
                    )
                    ms.touch_session(req.session_id)
                request = event.get("request") or {}
                action_requests = request.get("action_requests", [])
                proposals = [
                    {"name": ar.get("name", ""), "args": ar.get("args", {}),
                     "description": ar.get("description", "")}
                    for ar in action_requests
                ]
                yield f"data: {json.dumps({'type': 'interrupt', 'session_id': req.session_id, 'proposals': proposals}, ensure_ascii=False)}\n\n"
                return
            elif event["type"] == "tool_start" and event.get("name"):
                # 同 stream：工具前的文本归档为 thought，保持交错顺序
                partial = "".join(answer_parts)
                if partial.strip():
                    timeline.append({"kind": "thought", "content": partial})
                    answer_parts = []
                timeline.append(
                    {"kind": "tool", "name": event["name"], "args": event.get("args", {}), "done": False}
                )
                record_metric(
                    ms, "tool_call", "count", 1,
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
                # 合并中断前的内容 + resume 后的内容，更新同一条待续消息
                full_answer = prev_content + answer
                merged_timeline = prev_timeline + timeline
                # memory 向量用全文（中断前 thought + resume thought + 最后文本）
                full_text = " \n".join(
                    [t["content"] for t in merged_timeline if t.get("kind") == "thought"]
                    + ([full_answer] if full_answer else [])
                )
                if pending_id is not None and (full_answer or merged_timeline):
                    # 更新待续消息（合并内容 + 标记完成）
                    ms.update_message(
                        pending_id, full_answer, timeline=merged_timeline, status="complete"
                    )
                    ms.set_pending_msg_id(req.session_id, None)
                    # 写入记忆向量（完整答案）
                    if full_text:
                        vs.add_memory(pending_id, req.session_id, "assistant", full_text)
                    ms.touch_session(req.session_id)
                elif answer:
                    # 无待续消息（异常情况）：退回新增一条
                    assistant_msg_id = ms.add_message(
                        req.session_id, "assistant", answer, timeline=timeline
                    )
                    vs.add_memory(assistant_msg_id, req.session_id, "assistant", answer)
                    ms.touch_session(req.session_id)
                elapsed_ms = round((_time.perf_counter() - _t0) * 1000, 1)
                record_metric(ms, "ask", "latency_ms", elapsed_ms,
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
# 会话管理
# ============================================================

@router.post("/sessions", response_model=SessionItem)
def create_session(req: SessionCreateRequest):
    """创建新会话。"""
    ms = get_metadata_store()
    session_id = uuid.uuid4().hex[:12]
    title = req.title or "新对话"
    ms.create_session(session_id, title=title)
    session = ms.get_session(session_id)
    return SessionItem(**session)


@router.get("/sessions", response_model=list[SessionItem])
def list_sessions():
    """列出全部会话。"""
    ms = get_metadata_store()
    sessions = ms.list_sessions()
    return [SessionItem(**s) for s in sessions]


@router.get("/sessions/{session_id}/messages", response_model=SessionMessagesResponse)
def get_session_messages(session_id: str):
    """获取会话的消息历史。"""
    ms = get_metadata_store()
    session = ms.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    messages = ms.get_messages(session_id)
    return SessionMessagesResponse(
        session_id=session_id,
        title=session["title"],
        messages=[MessageItem(**m) for m in messages],
    )


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str):
    """删除会话（含全部消息和记忆向量）。"""
    ms = get_metadata_store()
    vs = get_vector_store()
    ms.delete_session(session_id)
    vs.delete_session_memory(session_id)
    return {"ok": True}


# ============================================================
# 知识片段
# ============================================================

@router.get("/fragments")
def list_fragments(limit: int = Query(50, ge=1, le=200)):
    """列出已保存的知识片段（HIL 确认后的沉淀内容）。"""
    return get_metadata_store().list_knowledge_fragments(limit=limit)


@router.delete("/fragments/{fragment_id}")
def delete_fragment(fragment_id: int):
    """删除知识片段（SQLite + 向量同步删除）。"""
    ms = get_metadata_store()
    vs = get_vector_store()
    ok = ms.delete_knowledge_fragment(fragment_id)
    if not ok:
        raise HTTPException(status_code=404, detail="片段不存在")
    vs.delete_fragment(fragment_id)
    return {"ok": True}
