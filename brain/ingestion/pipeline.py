"""LangGraph 摄入流水线。

Phase 2: parse → chunk → embed → classify → connect → index
                                                      └─ 并行(非关键节点) ─┘
"""

import uuid
from datetime import datetime
from pathlib import Path

from langgraph.graph import END, StateGraph
from loguru import logger
from typing_extensions import TypedDict

from brain.agents.classifier import ClassifierAgent
from brain.agents.connector import ConnectorAgent
from brain.ingestion.chunker import SemanticChunker
from brain.ingestion.parser import DocumentParser
from brain.models import (
    Chunk,
    Connection,
    NoteMetadata,
    ParsedDocument,
    SourceType,
    Tag,
)
from brain.storage.metadata import MetadataStore
from brain.storage.vector_store import VectorStore


class IngestionState(TypedDict):
    """摄入流水线的共享状态。每个节点读写这个字典。"""

    # 输入
    source_path: str
    raw_text: str
    source_type: str  # 可选：显式指定来源类型（如 bookmark），空则按 source_path 推断

    # 中间产物
    parsed_doc: ParsedDocument | None
    chunks: list[Chunk]
    tags: list[Tag]  # Phase 2: AI 生成的标签
    connections: list[Connection]  # Phase 2: 发现的关联

    # 输出
    note_id: str

    # 追踪
    errors: list[str]
    status: str  # "running" | "completed" | "failed"


class IngestionPipeline:
    """摄入流水线 — parse → chunk → embed → classify → connect → index"""

    def __init__(
        self,
        vector_store: VectorStore,
        metadata_store: MetadataStore,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
    ):
        self.vector_store = vector_store
        self.metadata_store = metadata_store
        self.parser = DocumentParser()
        self.chunker = SemanticChunker(max_chunk_size=chunk_size, overlap_size=chunk_overlap)

        # Phase 2: Agent 懒加载
        self._classifier: ClassifierAgent | None = None
        self._connector: ConnectorAgent | None = None

        self._graph = self._build_graph()

    # ---- 公共接口 ----

    async def ingest_file(self, file_path: Path) -> str:
        """摄入一个 Markdown 文件。"""
        raw_text = file_path.read_text(encoding="utf-8")
        state: IngestionState = {
            "source_path": str(file_path),
            "raw_text": raw_text,
            "source_type": "",
            "parsed_doc": None,
            "chunks": [],
            "tags": [],
            "connections": [],
            "note_id": "",
            "errors": [],
            "status": "running",
        }
        final_state = await self._graph.ainvoke(state)
        return final_state["note_id"]

    def ingest_file_sync(self, file_path: Path) -> str:
        """摄入文件（同步版本，供非异步上下文调用）。"""
        from brain.observability import MetricsTimer, record_metric

        with MetricsTimer(self.metadata_store, "ingest", "latency_ms", {"source": "file"}):
            raw_text = file_path.read_text(encoding="utf-8")
            state: IngestionState = {
                "source_path": str(file_path), "raw_text": raw_text,
                "source_type": "",
                "parsed_doc": None, "chunks": [], "tags": [], "connections": [],
                "note_id": "", "errors": [], "status": "running",
            }
            final_state = self._graph.invoke(state)
        record_metric(self.metadata_store, "ingest", "count", 1, {"source": "file"})
        return final_state["note_id"]

    async def ingest_text(self, text: str, title: str | None = None) -> str:
        """摄入一段纯文本。"""
        state: IngestionState = {
            "source_path": "",
            "raw_text": f"# {title}\n\n{text}" if title else text,
            "source_type": "",
            "parsed_doc": None,
            "chunks": [],
            "tags": [],
            "connections": [],
            "note_id": "",
            "errors": [],
            "status": "running",
        }
        final_state = await self._graph.ainvoke(state)
        return final_state["note_id"]

    def ingest_text_sync(self, text: str, title: str | None = None, source_type: SourceType | None = None) -> str:
        """摄入文本（同步版本）。

        Args:
            source_type: 显式指定来源类型（如书签导入传 BOOKMARK），
                         None 则默认按 CLI 类型处理
        """
        state: IngestionState = {
            "source_path": "",
            "raw_text": f"# {title}\n\n{text}" if title else text,
            "source_type": source_type.value if source_type else "",
            "parsed_doc": None, "chunks": [], "tags": [], "connections": [],
            "note_id": "", "errors": [], "status": "running",
        }
        final_state = self._graph.invoke(state)
        return final_state["note_id"]

    # ---- 构建 LangGraph ----

    def _build_graph(self) -> StateGraph:
        graph = StateGraph(IngestionState)

        # 关键节点
        graph.add_node("parse", self._parse_node)
        graph.add_node("chunk", self._chunk_node)
        graph.add_node("embed", self._embed_node)

        # Phase 2: 智能处理节点（非关键，失败不阻塞）
        graph.add_node("classify", self._classify_node)
        graph.add_node("connect", self._connect_node)

        # 元数据写入
        graph.add_node("index", self._index_node)

        # 流程: parse → chunk → embed → classify → connect → index
        graph.set_entry_point("parse")
        graph.add_edge("parse", "chunk")
        graph.add_edge("chunk", "embed")
        graph.add_edge("embed", "classify")
        graph.add_edge("classify", "connect")
        graph.add_edge("connect", "index")
        graph.add_edge("index", END)

        return graph.compile()

    # ================================================================
    # Phase 1 节点（保持不变）
    # ================================================================

    def _parse_node(self, state: IngestionState) -> IngestionState:
        t0 = datetime.now()
        try:
            if state["source_path"]:
                doc = self.parser.parse_file(Path(state["source_path"]))
            else:
                doc = self.parser.parse_text(state["raw_text"])

            state["parsed_doc"] = doc
            # 生成唯一 note_id，供后续所有节点使用（chunk/embed/classify/connect/index）
            state["note_id"] = uuid.uuid4().hex[:12]

            elapsed = (datetime.now() - t0).total_seconds() * 1000
            logger.info(f"[parse] ✓ {doc.title} ({len(doc.content)} 字符, {elapsed:.0f}ms)")
        except Exception as e:
            state["errors"].append(f"parse: {e}")
            state["status"] = "failed"
            logger.error(f"[parse] ✗ {e}")

        return state

    def _chunk_node(self, state: IngestionState) -> IngestionState:
        if state["status"] == "failed":
            return state

        t0 = datetime.now()
        try:
            doc = state["parsed_doc"]
            chunks = self.chunker.chunk(state["note_id"], doc.content)
            state["chunks"] = chunks

            elapsed = (datetime.now() - t0).total_seconds() * 1000
            logger.info(f"[chunk] ✓ {len(chunks)} 个分块 ({elapsed:.0f}ms)")
        except Exception as e:
            state["errors"].append(f"chunk: {e}")
            state["status"] = "failed"
            logger.error(f"[chunk] ✗ {e}")

        return state

    def _embed_node(self, state: IngestionState) -> IngestionState:
        if state["status"] == "failed":
            return state

        t0 = datetime.now()
        try:
            chunks = state["chunks"]
            if chunks:
                doc = state["parsed_doc"]
                for chunk in chunks:
                    chunk.metadata["title"] = doc.title
                    chunk.metadata["source_path"] = state["source_path"] or "cli"

                self.vector_store.add(chunks)

            elapsed = (datetime.now() - t0).total_seconds() * 1000
            logger.info(f"[embed] ✓ {len(chunks)} 个分块已嵌入 ({elapsed:.0f}ms)")
        except Exception as e:
            state["errors"].append(f"embed: {e}")
            state["status"] = "failed"
            logger.error(f"[embed] ✗ {e}")

        return state

    # ================================================================
    # Phase 2 节点 — 智能处理（非关键，失败不阻塞）
    # ================================================================

    def _classify_node(self, state: IngestionState) -> IngestionState:
        """节点4: DeepAgents 自动分类。非关键——失败不阻塞流水线。"""
        if state["status"] == "failed":
            return state

        t0 = datetime.now()
        try:
            doc = state["parsed_doc"]
            if not doc or not doc.content:
                return state

            if self._classifier is None:
                self._classifier = ClassifierAgent()

            result = self._classifier.run(
                note_title=doc.title,
                content=doc.content,
            )
            tags = ClassifierAgent.to_tags(result)
            state["tags"] = tags

            elapsed = (datetime.now() - t0).total_seconds() * 1000
            tag_names = [t.name for t in tags]
            logger.info(f"[classify] ✓ {tag_names} ({elapsed:.0f}ms)")
        except Exception as e:
            state["errors"].append(f"classify: {e}")
            logger.warning(f"[classify] ⚠ 分类失败（非致命）: {e}")

        return state

    def _connect_node(self, state: IngestionState) -> IngestionState:
        """节点5: DeepAgents 关联发现。非关键——失败不阻塞流水线。"""
        if state["status"] == "failed":
            return state

        t0 = datetime.now()
        try:
            doc = state["parsed_doc"]
            if not doc or not doc.content:
                return state

            # 1. 向量粗筛：找 Top 20 候选笔记
            candidates = self._find_candidates(doc)
            if not candidates:
                logger.info("[connect] ✓ 无候选笔记，跳过")
                return state

            # 2. DeepAgents 深度分析
            if self._connector is None:
                self._connector = ConnectorAgent()

            result = self._connector.run(
                new_note_title=doc.title,
                new_note_content=doc.content,
                candidates=candidates,
            )
            connections = ConnectorAgent.to_connections(
                result, source_note_id=state["note_id"]
            )
            state["connections"] = connections

            elapsed = (datetime.now() - t0).total_seconds() * 1000
            logger.info(
                f"[connect] ✓ 发现 {len(connections)} 条关联 ({elapsed:.0f}ms)"
            )
        except Exception as e:
            state["errors"].append(f"connect: {e}")
            logger.warning(f"[connect] ⚠ 关联发现失败（非致命）: {e}")

        return state

    def _find_candidates(self, doc: ParsedDocument, top_k: int = 20) -> list[dict]:
        """向量粗筛——找到与新笔记最相似的历史笔记。

        排除两种"自己":
          1. 同 note_id 的重复命中（向量检索同笔记多 chunk 命中）
          2. 同 file_hash 的旧版本（同一文件修改后重新摄入时，
             旧版本内容几乎相同，会被向量检索命中但其实是自己）
        """
        # 查询用标题 + 前 300 字符——BGE 模型最大 512 token 限制
        query = f"{doc.title} {doc.content[:300]}"
        results = self.vector_store.search(query, top_k=top_k * 2)

        if not results:
            return []

        seen = set()
        candidates = []
        for r in results:
            if r.note_id in seen:
                continue
            seen.add(r.note_id)

            # 排除 file_hash 相同的旧版本（同一文件的先前摄入）
            if doc.file_hash:
                existing = self.metadata_store.get_note(r.note_id)
                if existing and existing.file_hash == doc.file_hash:
                    continue

            candidates.append(
                {
                    "note_id": r.note_id,
                    "title": r.note_title,
                    "content": r.content,
                }
            )
            if len(candidates) >= top_k:
                break

        return candidates

    # ================================================================
    # Phase 1 节点 — 元数据写入（扩展了 tags 和 connections）
    # ================================================================

    def _index_node(self, state: IngestionState) -> IngestionState:
        """节点6: 写入元数据（SQLite）——含标签和关联。"""
        if state["status"] == "failed":
            return state

        t0 = datetime.now()
        try:
            doc = state["parsed_doc"]
            chunks = state["chunks"]
            tags = state.get("tags", [])
            connections = state.get("connections", [])
            now = datetime.now().isoformat()

            # 检查是否已存在（按 file_hash）
            if doc.file_hash:
                existing_id = self.metadata_store.note_exists(doc.file_hash)
                if existing_id:
                    logger.info(
                        f"[index] ⊘ 笔记已存在，跳过: {doc.title} ({existing_id})"
                    )
                    state["note_id"] = existing_id
                    state["status"] = "completed"
                    return state

            # source_type 优先用显式传入（如书签），否则按 source_path 推断（文件=MARKDOWN，空=CLI）
            explicit_type = state.get("source_type", "")
            if explicit_type:
                source_type = SourceType(explicit_type)
            else:
                source_type = SourceType.MARKDOWN if state["source_path"] else SourceType.CLI

            note_id = state["note_id"]  # 由 _parse_node 生成，所有节点共用

            content_preview = doc.content[:200]
            if len(doc.content) > 200:
                content_preview += "..."

            note = NoteMetadata(
                id=note_id,
                title=doc.title,
                source_type=source_type,
                source_path=state["source_path"] or None,
                file_hash=doc.file_hash,
                content_preview=content_preview,
                content_length=len(doc.content),
                chunk_count=len(chunks),
                created_at=now,
                updated_at=now,
                ingested_at=now,
            )
            self.metadata_store.create_note(note)

            # Phase 2: 写入 AI 标签
            for tag in tags:
                try:
                    tag_id = self.metadata_store.get_or_create_tag(
                        name=tag.name,
                        category=tag.category,
                        is_ai=tag.is_ai_generated,
                    )
                    self.metadata_store.add_tag_to_note(
                        note_id=note_id,
                        tag_id=tag_id,
                        confidence=tag.confidence,
                    )
                except Exception as e:
                    logger.warning(f"[index] 标签写入失败 ({tag.name}): {e}")

            # Phase 2: 写入关联
            for conn in connections:
                conn.source_note_id = note_id
                conn.is_ai_generated = True
                try:
                    self.metadata_store.add_connection(conn)
                except Exception as e:
                    logger.warning(f"[index] 关联写入失败: {e}")

            self.metadata_store.log_event(
                note_id=note_id,
                event="ingestion_complete",
                status="success",
                message=(
                    f"分块 {len(chunks)}, "
                    f"标签 {len(tags)}, "
                    f"关联 {len(connections)}, "
                    f"内容 {len(doc.content)} 字符"
                ),
                duration_ms=int((datetime.now() - t0).total_seconds() * 1000),
            )

            state["status"] = "completed"
            elapsed = (datetime.now() - t0).total_seconds() * 1000
            logger.info(f"[index] ✓ {note_id[:8]}... ({elapsed:.0f}ms)")
        except Exception as e:
            state["errors"].append(f"index: {e}")
            state["status"] = "failed"
            logger.error(f"[index] ✗ {e}")

        return state
