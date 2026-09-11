"""深度研究 Agent — 基于 DeepAgents 框架 + 官方 AgentMiddleware。"""

from langchain_core.tools import tool
from loguru import logger

from brain.agents.middleware import LoggingMiddleware
from brain.llm import get_chat_model
from brain.prompts import get_prompt
from brain.storage.metadata import MetadataStore
from brain.storage.vector_store import VectorStore


class ResearcherAgent:
    """DeepAgents 深度研究 Agent。"""

    def __init__(
        self,
        vector_store: VectorStore,
        metadata_store: MetadataStore,
        hybrid_searcher=None,
    ):
        self._vector_store = vector_store
        self._metadata_store = metadata_store
        # Phase 5F：注入混合检索器（BM25+向量+RRF+Rerank+查询改写）
        # 为 None 时 search_notes 工具回退到纯向量检索（向后兼容）
        self._hybrid_searcher = hybrid_searcher

    def research_sync(
        self,
        question: str,
        session_id: str | None = None,
        history: list[dict] | None = None,
        trace_id: str | None = None,
    ) -> str:
        """同步执行深度研究。"""
        return self._do_research(question, session_id, history, trace_id=trace_id)

    async def research(self, question: str, session_id: str | None = None) -> str:
        """异步执行深度研究。"""
        return self._do_research(question, session_id)

    def _build_agent(self, session_id: str | None = None, checkpointer=None, trace_id: str | None = None):
        """构建 DeepAgent（复用逻辑）。

        主 Agent 配备:
          - 4 个知识库工具（搜索/详情/关联/标签）
          - title-writer 子智能体: 自己写标题入库
          - knowledge-extractor 子智能体: 提取知识片段，经用户确认后保存

        HIL: propose_knowledge 工具注册在 interrupt_on，
        用户批准(approve)后才真正执行保存。

        Args:
            trace_id: 可观测性 trace_id，用于 LLM token 跟踪回调（Phase 5A）
        """
        self._trace_id = trace_id  # 供 stream config 的 token 回调使用
        tools = self._build_tools()
        llm = get_chat_model()
        ms = self._metadata_store
        vs = self._vector_store

        from deepagents import SubAgent, create_deep_agent

        # 子智能体的标题写入工具——闭包捕获 session_id
        @tool
        def update_session_title(title: str) -> str:
            """更新当前会话的标题。

            Args:
                title: 新标题，不超过 10 个字
            """
            if not session_id:
                return "错误: 当前没有关联的会话"
            clean_title = title.strip()[:10]
            ms.rename_session(session_id, clean_title)
            logger.info(f"[title-writer] 会话标题已入库: {clean_title}")
            return f"会话标题已更新为: {clean_title}"

        title_writer = SubAgent(
            name="title-writer",
            description="为当前对话生成简短标题（10 字以内）并写入数据库。当需要为对话命名时调用。",
            system_prompt=get_prompt("title_writer"),
            tools=[update_session_title],
        )

        # ---- 知识片段提取子智能体 ----
        # propose_knowledge 会被 interrupt_on 拦截：用户批准后才真正执行保存

        @tool
        def propose_knowledge(title: str, content: str) -> str:
            """提议保存一条知识片段（需要用户批准后才会执行）。

            Args:
                title: 片段标题（不超过 20 字）
                content: 片段内容（一段话，可含多个要点）
            """
            clean_title = title.strip()[:20]
            clean_content = content.strip()
            fragment_id = ms.add_knowledge_fragment(
                title=clean_title, content=clean_content, session_id=session_id
            )
            # 同步写入向量（供语义检索）
            vs.add_fragment(fragment_id, clean_title, clean_content)
            logger.info(f"[knowledge-extractor] 知识片段已保存: {title}")
            return f"知识片段「{title}」已保存。"

        @tool
        def check_existing_fragments(title: str) -> str:
            """检查是否已有相同标题的知识片段（去重用）。

            Args:
                title: 要检查的标题
            """
            existing = ms.find_similar_fragment(title.strip())
            if existing:
                return f"已存在相同标题的片段: 「{existing['title']}」\n内容: {existing['content'][:200]}"
            return "没有找到相同标题的片段。"

        knowledge_extractor = SubAgent(
            name="knowledge-extractor",
            description=(
                "从最近几轮对话中提取值得长期保存的知识片段（结论、事实、经验），"
                "检查去重后提议给用户确认。当对话中产生了有价值的知识时调用。"
            ),
            system_prompt=get_prompt("knowledge_extractor"),
            tools=[check_existing_fragments, propose_knowledge],
        )

        return create_deep_agent(
            model=llm,
            tools=tools,
            subagents=[title_writer, knowledge_extractor],
            # HIL：propose_knowledge 调用时暂停，等待用户批准/编辑/拒绝
            interrupt_on={"propose_knowledge": True},
            checkpointer=checkpointer,
            system_prompt=get_prompt("researcher"),
            middleware=[LoggingMiddleware(agent_name="researcher")],
        )

    def research_stream(
        self,
        question: str,
        session_id: str | None = None,
        history: list[dict] | None = None,
        memory_hits: list | None = None,
        checkpointer=None,
        trace_id: str | None = None,
    ):
        """流式执行研究，逐事件 yield。

        Args:
            question: 当前用户问题
            session_id: 会话 ID（供子智能体写标题用）
            history: 历史消息列表 [{"role": "user"/"assistant", "content": ...}]
                     不含当前问题，按时间正序
            memory_hits: 跨会话检索到的相关历史消息（SearchResult 列表）

        Yield 事件类型:
          - {"type": "status", "message": str}         状态提示（Agent 启动/完成）
          - {"type": "tool_start", "name": str, "args": dict}  工具开始调用
          - {"type": "tool_end", "name": str}                工具调用完成
          - {"type": "token", "content": str}                答案 token 流
          - {"type": "interrupt", "request": dict}           HIL 中断（等待用户决策）
          - {"type": "done", "content": str}                 完成（完整答案）
        """
        agent = self._build_agent(session_id, checkpointer=checkpointer, trace_id=trace_id)

        # 组装多轮消息列表：系统上下文 + 历史 + 当前问题
        messages: list[dict] = []

        # 第二层记忆：相关历史消息以 system 注入（同会话旧消息标记"本会话"）
        if memory_hits:
            memory_section = "\n".join(
                f"- [{m.note_title}{'(本会话)' if m.metadata.get('is_current_session') else ''}] {m.content[:200]}"
                for m in memory_hits
            )
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "以下是你在过往对话中讨论过的相关内容（检索记忆），"
                        "回答时可参考，但用户没有明确提及时不要主动大段复述：\n"
                        f"{memory_section}"
                    ),
                }
            )

        if history:
            for h in history[-20:]:  # 最近 10 轮（20 条），防止上下文过长
                messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": question})

        logger.info(
            f"[researcher] 开始流式研究: {question} "
            f"(含 {len(messages) - 1} 条上下文消息, {len(memory_hits or [])} 条跨会话记忆)"
        )

        yield {"type": "status", "message": "🤔 Agent 启动，正在思考..."}

        # stream_mode=["messages", "updates"]:
        #   - messages: LLM 输出的 token 流和 tool_calls
        #   - updates: 工具执行结果（tools 节点）
        #
        # LangGraph 流式模式下 tool_calls 是分片的：
        #   第一个 chunk 带 name（args 为空），后续 chunk 带 args（name 为空）。
        # 需要按 index 累积合并，避免产生空 name 的事件。
        pending_tool_calls: dict[int, dict] = {}

        # thread_id = session_id：HIL 中断后可用同一 thread_id 恢复
        stream_config = (
            {"configurable": {"thread_id": session_id}} if checkpointer and session_id else {}
        )
        # recursion_limit 防死循环（Phase 5B FR48）
        from brain.config import get_config
        stream_config["recursion_limit"] = get_config().cost.recursion_limit
        # 注入 token 跟踪回调（Phase 5A）
        if self._trace_id:
            from brain.observability import TraceEventLogger
            token_cb = TraceEventLogger(self._metadata_store, self._trace_id)
            stream_config.setdefault("callbacks", []).append(token_cb)
        # Phase 5G：Langfuse 追踪——与本地 TraceEventLogger 并存，互不干扰
        # agent.stream 是 chain 路径，触发 on_chain_start，CallbackHandler 从 metadata
        # 的 langfuse_* 前缀自动解析 trace 属性（trace_name/session_id/tags）
        from brain.langfuse_tracing import attach_langfuse
        stream_config = attach_langfuse(
            stream_config,
            session_id=session_id,
            trace_id=self._trace_id,
            trace_name="ask",
            tags=["deepagents", "rag"],
        )

        for mode, chunk in agent.stream(
            {"messages": messages},
            config=stream_config,
            stream_mode=["messages", "updates"],
        ):
            if mode == "messages":
                msg, meta = chunk
                content = getattr(msg, "content", None)
                tool_calls = getattr(msg, "tool_calls", None)

                # 只把「模型节点」的 AIMessage 内容作为答案 token 输出。
                # 工具返回值（ToolMessage / 带 tool_call_id 的消息）不应混入答案。
                source_node = meta.get("langgraph_node", "") if isinstance(meta, dict) else ""
                class_name = msg.__class__.__name__
                has_tool_call_id = bool(getattr(msg, "tool_call_id", None))
                is_model_output = (
                    class_name in ("AIMessage", "AIMessageChunk")
                    and source_node != "tools"
                    and not has_tool_call_id
                )

                if content and is_model_output:
                    yield {"type": "token", "content": content}

                if tool_calls:
                    for tc in tool_calls:
                        tc_index = tc.get("index", 0)
                        entry = pending_tool_calls.get(tc_index)
                        # 上一回合同 index 的工具已发送 → 新回合的工具调用，重置 entry
                        if entry and entry.get("_sent"):
                            entry = {"name": "", "args": {}, "id": ""}
                        if not entry:
                            entry = {"name": "", "args": {}, "id": ""}
                        pending_tool_calls[tc_index] = entry
                        if tc.get("name"):
                            entry["name"] = tc["name"]
                        if tc.get("id"):
                            entry["id"] = tc["id"]
                        # args 到达就更新（流式下 name 和 args 可能分片到达）
                        if tc.get("args") is not None:
                            entry["args"] = {**entry["args"], **tc["args"]}

                        # name 到达就发出事件（带上当前 args，可能后续才补全）
                        if entry["name"] and not entry.get("_sent"):
                            yield {
                                "type": "tool_start",
                                "name": entry["name"],
                                "args": entry["args"],
                            }
                            entry["_sent"] = True  # 标记已发送，避免同回合重复

            elif mode == "updates":
                # HIL 中断检测：__interrupt__ 键出现表示等待用户决策
                if "__interrupt__" in chunk:
                    interrupt_list = chunk["__interrupt__"]
                    for interrupt_obj in interrupt_list:
                        request = getattr(interrupt_obj, "value", None)
                        if request:
                            yield {"type": "interrupt", "request": request}
                    # 中断发生，流在此暂停（等待 /api/ask/resume 恢复）
                    yield {"type": "status", "message": "⏸ 等待用户确认知识片段..."}
                    return

                # 工具节点完成
                for node, update in chunk.items():
                    if not update:
                        continue
                    if node == "tools" or "messages" in update:
                        for m in update.get("messages", []):
                            tool_call_id = getattr(m, "tool_call_id", None)
                            if not tool_call_id:
                                continue
                            tool_name = getattr(m, "name", "") or ""
                            final_args = {}
                            # name 为空时用 tool_call_id 从 pending 反查
                            if not tool_name:
                                for entry in pending_tool_calls.values():
                                    if entry.get("id") == tool_call_id:
                                        tool_name = entry.get("name", "")
                                        final_args = entry.get("args", {})
                                        break
                            else:
                                for entry in pending_tool_calls.values():
                                    if entry.get("name") == tool_name and entry.get("_sent"):
                                        final_args = entry.get("args", {})
                                        break
                            if tool_name:
                                yield {
                                    "type": "tool_end",
                                    "name": tool_name,
                                    "args": final_args,
                                }

        yield {"type": "status", "message": "✅ 研究完成"}
        yield {"type": "done", "content": ""}

    def resume_stream(
        self,
        session_id: str,
        decision: dict,
        checkpointer=None,
        trace_id: str | None = None,
    ):
        """HIL 决策后恢复 Agent 执行，继续流式输出。

        Args:
            session_id: 会话 ID（作为 thread_id 定位 checkpoint）
            decision: HIL 决策，格式 {"decisions": [{"type": "approve"|"edit"|"reject", ...}]}
            checkpointer: 与初始流相同的 checkpointer 实例
            trace_id: 可观测性 trace_id（Phase 5A）
        """
        from langgraph.types import Command

        agent = self._build_agent(session_id, checkpointer=checkpointer, trace_id=trace_id)
        config = {"configurable": {"thread_id": session_id}}
        # recursion_limit 防死循环（Phase 5B FR48）
        from brain.config import get_config
        config["recursion_limit"] = get_config().cost.recursion_limit
        # 注入 token 跟踪回调（Phase 5A）
        if self._trace_id:
            from brain.observability import TraceEventLogger
            config.setdefault("callbacks", []).append(
                TraceEventLogger(self._metadata_store, self._trace_id)
            )
        # Phase 5G：Langfuse 追踪 HIL 恢复——归入同一 session，trace_name 标记 resume
        from brain.langfuse_tracing import attach_langfuse
        config = attach_langfuse(
            config,
            session_id=session_id,
            trace_id=self._trace_id,
            trace_name="ask-resume",
            tags=["deepagents", "rag", "hil-resume"],
        )

        logger.info(f"[researcher] 恢复执行 (session={session_id})")

        pending_tool_calls: dict[int, dict] = {}

        for mode, chunk in agent.stream(
            Command(resume=decision),
            config=config,
            stream_mode=["messages", "updates"],
        ):
            if mode == "messages":
                msg, meta = chunk
                content = getattr(msg, "content", None)
                tool_calls = getattr(msg, "tool_calls", None)

                source_node = meta.get("langgraph_node", "") if isinstance(meta, dict) else ""
                class_name = msg.__class__.__name__
                has_tool_call_id = bool(getattr(msg, "tool_call_id", None))
                is_model_output = (
                    class_name in ("AIMessage", "AIMessageChunk")
                    and source_node != "tools"
                    and not has_tool_call_id
                )

                if content and is_model_output:
                    yield {"type": "token", "content": content}

                if tool_calls:
                    for tc in tool_calls:
                        tc_index = tc.get("index", 0)
                        entry = pending_tool_calls.get(tc_index)
                        if entry and entry.get("_sent"):
                            entry = {"name": "", "args": {}, "id": ""}
                        if not entry:
                            entry = {"name": "", "args": {}, "id": ""}
                        pending_tool_calls[tc_index] = entry
                        if tc.get("name"):
                            entry["name"] = tc["name"]
                        if tc.get("id"):
                            entry["id"] = tc["id"]
                        if tc.get("args") is not None:
                            entry["args"] = {**entry["args"], **tc["args"]}
                        if entry["name"] and not entry.get("_sent"):
                            yield {
                                "type": "tool_start",
                                "name": entry["name"],
                                "args": entry["args"],
                            }
                            entry["_sent"] = True

            elif mode == "updates":
                if "__interrupt__" in chunk:
                    for interrupt_obj in chunk["__interrupt__"]:
                        request = getattr(interrupt_obj, "value", None)
                        if request:
                            yield {"type": "interrupt", "request": request}
                    yield {"type": "status", "message": "⏸ 等待用户确认知识片段..."}
                    return

                for node, update in chunk.items():
                    if not update:
                        continue
                    if node == "tools" or "messages" in update:
                        for m in update.get("messages", []):
                            tool_call_id = getattr(m, "tool_call_id", None)
                            if not tool_call_id:
                                continue
                            tool_name = getattr(m, "name", "") or ""
                            final_args = {}
                            if not tool_name:
                                for entry in pending_tool_calls.values():
                                    if entry.get("id") == tool_call_id:
                                        tool_name = entry.get("name", "")
                                        final_args = entry.get("args", {})
                                        break
                            else:
                                for entry in pending_tool_calls.values():
                                    if entry.get("name") == tool_name and entry.get("_sent"):
                                        final_args = entry.get("args", {})
                                        break
                            if tool_name:
                                yield {
                                    "type": "tool_end",
                                    "name": tool_name,
                                    "args": final_args,
                                }

        yield {"type": "status", "message": "✅ 研究完成"}
        yield {"type": "done", "content": ""}

    def _do_research(
        self,
        question: str,
        session_id: str | None = None,
        history: list[dict] | None = None,
        trace_id: str | None = None,
    ) -> str:
        agent = self._build_agent(session_id, trace_id=trace_id)

        # 组装多轮消息列表：历史 + 当前问题
        messages: list[dict] = []
        if history:
            for h in history[-20:]:
                messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": question})

        logger.info(
            f"[researcher] 开始研究: {question} (含 {len(messages) - 1} 条历史消息)"
        )
        invoke_config = {}
        # recursion_limit 防死循环（Phase 5B FR48）
        from brain.config import get_config
        invoke_config["recursion_limit"] = get_config().cost.recursion_limit
        if self._trace_id:
            from brain.observability import TraceEventLogger
            invoke_config["callbacks"] = [
                TraceEventLogger(self._metadata_store, self._trace_id)
            ]
        # Phase 5G：Langfuse 追踪（非流式问答，chain 路径用 metadata 模式）
        from brain.langfuse_tracing import attach_langfuse
        invoke_config = attach_langfuse(
            invoke_config,
            session_id=session_id,
            trace_id=self._trace_id,
            trace_name="ask",
            tags=["deepagents", "rag"],
        )
        result = agent.invoke({"messages": messages}, config=invoke_config or None)

        result_messages = result.get("messages", [])
        if result_messages:
            answer = result_messages[-1].content
            logger.info(f"[researcher] ✓ 研究完成 ({len(answer)} 字符)")
            return answer

        return "研究未能得出结果。"

    def _build_tools(self) -> list:
        vs = self._vector_store
        ms = self._metadata_store
        hs = self._hybrid_searcher  # Phase 5F 混合检索器（可能为 None）

        @tool
        def search_notes(query: str, top_k: int = 5) -> str:
            """语义搜索知识库，返回最相关的笔记片段。"""
            # Phase 5F：优先用混合检索（BM25+向量+RRF+Rerank），无则回退纯向量
            if hs is not None:
                results = hs.search(query, top_k=top_k)
            else:
                results = vs.search(query, top_k=top_k)
            if not results:
                return "未找到相关笔记。"
            lines = []
            for i, r in enumerate(results, 1):
                title = r.note_title or r.metadata.get("title", "无标题")
                lines.append(
                    f"{i}. [{title}] (相似度: {r.score:.2f}, id: {r.note_id})\n"
                    f"   {r.content[:300]}..."
                )
            return "\n\n".join(lines)

        @tool
        def search_fragments(keyword: str, limit: int = 5) -> str:
            """搜索已沉淀的知识片段（此前对话中经用户确认保存的结论）。

            当用户询问"我之前总结过什么"或需要引用过往对话沉淀的结论时使用。
            语义检索——不需要精确关键词，意思相近即可命中。

            Args:
                keyword: 搜索关键词或描述
                limit: 返回条数（默认 5）
            """
            results = vs.search_fragments(keyword, top_k=limit)
            if not results:
                return f"没有找到与 '{keyword}' 相关的知识片段。"

            lines = ["沉淀的知识片段:\n"]
            for i, r in enumerate(results, 1):
                frag_id = r.note_id  # 向量里存的 fragment_id
                lines.append(
                    f"{i}. 【{r.note_title}】(片段 #{frag_id}, 相似度 {r.score:.2f})\n"
                    f"   {r.content[:400]}"
                )
            return "\n\n".join(lines)

        @tool
        def get_note_detail(note_id: str) -> str:
            """获取某条笔记的详细信息（完整内容和标签）。"""
            note = ms.get_note(note_id)
            title = note.title if note else "未知笔记"
            tags = ms.get_note_tags(note_id) if note else []
            tag_str = ", ".join(t.name for t in tags) if tags else "无标签"

            # 精确取回全部正文分块（按 chunk_index 排序拼接），
            # 不做语义搜索——ID 字符串语义搜索是碰运气
            chunks = vs.get_note_chunks(note_id)
            content = "".join(c.content for c in chunks) if chunks else "(内容未找到)"
            return f"标题: {title}\n标签: {tag_str}\n内容: {content}"

        @tool
        def get_connections(note_id: str) -> str:
            """获取某条笔记的关联笔记链。"""
            conns = ms.get_connections(note_id)
            if not conns:
                return "此笔记暂无关联。"

            lines = [f"共 {len(conns)} 条关联:\n"]
            for i, c in enumerate(conns, 1):
                other_id = c.target_note_id if c.source_note_id == note_id else c.source_note_id
                other_note = ms.get_note(other_id)
                other_title = other_note.title if other_note else other_id[:8]
                lines.append(
                    f"{i}. [{c.relation_type.value}] → {other_title}\n"
                    f"   说明: {c.description or '无'}\n"
                    f"   强度: {c.strength:.0%}"
                )
            return "\n".join(lines)

        @tool
        def search_by_tag(tag_name: str) -> str:
            """按标签查找笔记（支持部分匹配）。"""
            # 一次 SQL JOIN 查询（list_notes_by_tag），避免 N+1 全表扫描
            notes = ms.list_notes_by_tag(tag_name, limit=20)
            if not notes:
                return f"未找到标签含 '{tag_name}' 的笔记。"

            # 批量取标签（一次 SQL），拼显示文本
            tags_map = ms.get_tags_batch([n.id for n in notes])
            matched = []
            for note in notes:
                tag_names = [t.name for t in tags_map.get(note.id, [])]
                matched.append(
                    f"- [{note.ingested_at[:10] if note.ingested_at else '?'}] "
                    f"{note.title}  [标签: {', '.join(tag_names)}]"
                )
            return "匹配的笔记:\n\n" + "\n".join(matched)

        return [search_notes, search_fragments, get_note_detail, get_connections, search_by_tag]
