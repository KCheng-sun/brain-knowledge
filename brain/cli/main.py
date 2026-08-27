"""Brain CLI — 个人知识管家的命令行入口。

用法:
    brain add "今天读到的好观点..."
    brain ingest ./notes/article.md
    brain search "RAG 优化策略"
    brain ask "我关于 Agent 架构的思考有哪些关键结论？"
    brain status
"""

import asyncio
import os
from pathlib import Path

import click
from loguru import logger

from brain.config import get_config
from brain.embedding import get_embedding_fn
from brain.ingestion.pipeline import IngestionPipeline
from brain.storage.metadata import MetadataStore
from brain.storage.vector_store import VectorStore

# ============================================================
# 全局初始化
# ============================================================


def _get_pipeline() -> IngestionPipeline:
    """懒加载摄入流水线（包含 vector_store 和 metadata_store 的初始化）。"""
    cfg = get_config()
    embedding_fn = get_embedding_fn()
    vector_store = VectorStore(persist_dir=cfg.storage.chroma_dir, embedding_fn=embedding_fn)
    metadata_store = MetadataStore(db_path=cfg.storage.db_path)
    # MetadataStore 是同步实现，直接初始化（无需事件循环包装）
    if not hasattr(_get_pipeline, "_metadata_initialized"):
        metadata_store.initialize()
        _get_pipeline._metadata_initialized = True

    pipeline = IngestionPipeline(
        vector_store=vector_store,
        metadata_store=metadata_store,
        chunk_size=cfg.ingestion.chunk_size,
        chunk_overlap=cfg.ingestion.chunk_overlap,
    )
    return pipeline


def _get_search_components():
    """懒加载搜索组件。"""
    cfg = get_config()
    embedding_fn = get_embedding_fn()
    vector_store = VectorStore(persist_dir=cfg.storage.chroma_dir, embedding_fn=embedding_fn)

    metadata_store = MetadataStore(db_path=cfg.storage.db_path)
    # MetadataStore 是同步实现，直接初始化
    if not hasattr(_get_search_components, "_md_initialized"):
        metadata_store.initialize()
        _get_search_components._md_initialized = True

    return vector_store, metadata_store


def _run_async(coro):
    """在当前或新的事件循环中运行异步协程。"""
    try:
        asyncio.get_running_loop()  # 探测是否有运行中的事件循环
        # 已有运行中的事件循环，用新线程运行
        import concurrent.futures
        import threading

        future = concurrent.futures.Future()

        def _run():
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            try:
                result = new_loop.run_until_complete(coro)
                future.set_result(result)
            except Exception as e:
                future.set_exception(e)
            finally:
                new_loop.close()

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        return future.result()
    except RuntimeError:
        # 没有运行中的事件循环，直接创建
        return asyncio.run(coro)


# ============================================================
# CLI 入口
# ============================================================


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="显示详细日志")
@click.option("--dry-run", is_flag=True, help="模拟运行，不实际调用 LLM")
@click.pass_context
def cli(ctx, verbose: bool, dry_run: bool):
    """Brain — 个人知识管家（第二大脑）

    本地优先、AI 驱动的知识管理系统。
    摄入你的笔记和想法，用自然语言搜索和提问。
    """
    ctx.ensure_object(dict)

    # 日志配置
    if verbose:
        logger.remove()
        logger.add(lambda msg: click.echo(msg, err=True), level="DEBUG", format="{message}")
    else:
        logger.remove()
        logger.add(lambda msg: click.echo(msg, err=True), level="INFO", format="{message}")
        # 抑制 ChromaDB / sentence-transformers 的内部日志
        import logging as std_logging

        for name in ["chromadb", "sentence_transformers", "transformers", "httpx", "urllib3"]:
            std_logging.getLogger(name).setLevel(std_logging.WARNING)

    if dry_run:
        cfg = get_config()
        cfg.dry_run = True

    ctx.obj["verbose"] = verbose


# ============================================================
# brain add — 快速添加笔记
# ============================================================


@cli.command()
@click.argument("text", required=True)
@click.option("--title", "-t", default=None, help="笔记标题（默认取文本第一行）")
def add(text: str, title: str | None):
    """快速添加一条笔记。

    \b
    示例:
      brain add "今天读了一篇关于 RAG 优化的文章，核心思路是..."
      brain add -t "RAG 优化笔记" "HyDE 方法通过假设性文档..."
    """
    pipeline = _get_pipeline()

    click.echo("📝 正在摄入...")
    note_id = _run_async(pipeline.ingest_text(text, title=title))
    click.echo(f"✅ 已摄入: {note_id}")


# ============================================================
# brain ingest — 批量导入文件
# ============================================================


@cli.command()
@click.argument("path", type=click.Path(exists=True))
def ingest(path: str):
    """摄入 Markdown 文件或目录。

    \b
    示例:
      brain ingest ./notes/article.md
      brain ingest ./notes/          # 摄入目录下所有 .md 文件
    """
    pipeline = _get_pipeline()
    target = Path(path)

    if target.is_file():
        if target.suffix != ".md":
            click.echo(f"⚠️  跳过非 Markdown 文件: {target.name}")
            return
        click.echo(f"📄 摄入: {target.name}")
        note_id = _run_async(pipeline.ingest_file(target))
        click.echo(f"✅ 完成: {note_id}")

    elif target.is_dir():
        md_files = list(target.rglob("*.md"))
        # 排除隐藏目录
        md_files = [f for f in md_files if not any(p.startswith(".") for p in f.parts)]
        click.echo(f"📂 发现 {len(md_files)} 个 Markdown 文件")

        for i, f in enumerate(md_files, 1):
            click.echo(f"  [{i}/{len(md_files)}] 摄入: {f.name}")
            try:
                note_id = _run_async(pipeline.ingest_file(f))
                click.echo(f"    ✅ {note_id}")
            except Exception as e:
                click.echo(f"    ❌ 失败: {e}")


# ============================================================
# brain search — 语义搜索
# ============================================================


@cli.command()
@click.argument("query", required=True)
@click.option("--top-k", "-k", default=5, help="返回结果数量 (默认 5)")
@click.option("--tag", "-t", default=None, help="按标签过滤 (例如 --tag \"AI Agent\")")
def search(query: str, top_k: int, tag: str | None):
    """语义搜索知识库。

    \b
    示例:
      brain search "RAG 优化策略"
      brain search -k 10 "Agent 架构设计"
      brain search --tag "Python" "异步编程"
    """
    vector_store, metadata_store = _get_search_components()

    # 标签过滤: 一次 SQL JOIN 查匹配标签的笔记（避免 N+1）
    tag_note_ids: set | None = None
    if tag:
        click.echo(f"🔍 搜索: {query}  [标签: {tag}]\n")
        matched_notes = metadata_store.list_notes_by_tag(tag, limit=10000)
        tag_note_ids = {n.id for n in matched_notes}
        if not tag_note_ids:
            click.echo(f"  没有标记为 '{tag}' 的笔记。")
            return
    else:
        click.echo(f"🔍 搜索: {query}\n")

    results = vector_store.search(query, top_k=max(top_k * 2, 20))

    if not results:
        click.echo("  没有找到相关结果。")
        return

    # 去重按 note_id，可选按标签过滤
    seen_notes: dict[str, list] = {}
    for r in results:
        if tag_note_ids is not None and r.note_id not in tag_note_ids:
            continue
        if r.note_id not in seen_notes:
            seen_notes[r.note_id] = []
        seen_notes[r.note_id].append(r)

    if not seen_notes:
        click.echo(f"  没有同时匹配查询和标签 '{tag}' 的结果。")
        return

    # 显示结果（带标签）
    for i, (note_id, chunks) in enumerate(seen_notes.items(), 1):
        if i > top_k:
            break
        best = max(chunks, key=lambda c: c.score)
        title = best.note_title or best.metadata.get("title", "无标题")

        # 获取标签用于显示
        note_tags = metadata_store.get_note_tags(note_id)
        tag_str = ""
        if note_tags:
            tag_names = [t.name for t in note_tags[:3]]
            tag_str = " [" + ", ".join(tag_names) + "]"

        click.echo(f"  {i}. [{best.score:.2f}] {title}{tag_str}")
        click.echo(f"     {best.content[:150].replace(chr(10), ' ')}...")
        click.echo(f"     id: {note_id}")
        click.echo()


# ============================================================
# brain ask — 深度问答
# ============================================================


@cli.command()
@click.argument("question", required=True)
@click.option("--simple", "-s", is_flag=True, help="使用简单 RAG 模式（不用 DeepAgents）")
def ask(question: str, simple: bool):
    """基于知识库的深度问答。

    \b
    默认使用 DeepAgents 多步推理（多次搜索 + 关联追踪）。
    示例:
      brain ask "我关于 Agent 架构的思考有哪些关键结论？"
      brain ask -s "ChromaDB 参数"    # 简单 RAG 模式
    """
    vector_store, metadata_store = _get_search_components()

    if simple:
        # 降级模式：简单 RAG
        _ask_simple(question, vector_store, metadata_store)
    else:
        # DeepAgents 模式：多步推理
        _ask_deep(question, vector_store, metadata_store)


def _ask_deep(question: str, vector_store, metadata_store) -> None:
    """DeepAgents 多步推理问答"""
    from brain.agents.researcher import ResearcherAgent

    click.echo("🧠 深度研究中...（多次搜索 + 关联追踪）")

    try:
        agent = ResearcherAgent(vector_store, metadata_store)
        answer = _run_async(agent.research(question))
        click.echo(f"\n{answer}\n")
    except Exception as e:
        click.echo(f"❌ DeepAgents 研究失败: {e}")
        click.echo("提示: 使用 brain ask -s 切换简单 RAG 模式。")


def _ask_simple(question: str, vector_store, metadata_store) -> None:
    """简单 RAG 模式（降级方案）"""
    results = vector_store.search(question, top_k=5)
    if not results:
        click.echo("  没有找到相关内容来回答这个问题。")
        return

    context_parts = []
    seen_notes = set()
    for r in results:
        if r.note_id not in seen_notes:
            seen_notes.add(r.note_id)
            context_parts.append(
                f"--- 来源: {r.note_title} (id: {r.note_id}) ---\n{r.content}"
            )
    context = "\n\n".join(context_parts)

    prompt = f"""你是一个个人知识库助手。基于用户的知识库内容回答问题。

知识库内容:
{context}

用户问题: {question}

请基于知识库内容回答。引用具体的来源（笔记标题）。
如果知识库中没有足够信息，请诚实说明。"""

    click.echo("🤔 思考中...")

    try:
        from brain.llm import get_chat_model

        llm = get_chat_model()
        response = llm.invoke(prompt)
        answer = response.content

        click.echo(f"\n{answer}\n")
        click.echo("📚 参考来源:")
        for r in results[:5]:
            click.echo(f"  • {r.note_title} (相似度: {r.score:.2f})")
    except Exception as e:
        click.echo(f"❌ LLM 调用失败: {e}")
        click.echo("提示: 检查 DEEPSEEK_API_KEY 环境变量是否已设置。")


# ============================================================
# brain status — 知识库统计
# ============================================================


@cli.command()
def status():
    """查看知识库统计信息。"""
    vector_store, metadata_store = _get_search_components()

    chunk_count = vector_store.count()
    note_count = metadata_store.count_notes()

    # 标签统计 / 关联总数——一次 SQL 完成，避免逐篇 N+1 遍历
    tag_counts = metadata_store.get_tag_counts()  # {tag_name: count}
    degree_map = metadata_store.get_note_degree_map()  # {note_id: 度数}
    # 每条关联在 degree_map 中被两端各计一次，总关联数 = 度数总和 / 2
    total_connections = sum(degree_map.values()) // 2

    click.echo("🧠 Brain 知识库状态\n")
    click.echo(f"  笔记总数:   {note_count}")
    click.echo(f"  分块总数:   {chunk_count}")
    click.echo(f"  AI 标签数:  {len(tag_counts)}")
    click.echo(f"  AI 关联数:  {total_connections}")

    # 热门标签
    if tag_counts:
        top_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:8]
        click.echo("\n🏷️  热门标签:")
        for name, count in top_tags:
            click.echo(f"  [{count}] {name}")

    # 最近笔记（仅 5 篇，单独取标签可接受）
    recent_notes = metadata_store.list_notes(limit=5)
    if recent_notes:
        # 一次 SQL 批量取标签，避免 5 次 get_note_tags
        tags_map = metadata_store.get_tags_batch([n.id for n in recent_notes])
        click.echo("\n📝 最近摄入的笔记:")
        for note in recent_notes:
            date_str = note.ingested_at[:10] if note.ingested_at else "未知"
            note_tags = tags_map.get(note.id, [])
            tag_str = ""
            if note_tags:
                tag_str = "  [" + ", ".join(t.name for t in note_tags[:3]) + "]"
            click.echo(f"  [{date_str}] {note.title}{tag_str}")


# ============================================================
# brain connections — 查看笔记关联
# ============================================================


@cli.command()
@click.option("--note-id", "-n", default=None, help="指定笔记 ID（不指定则列出全部）")
def connections(note_id: str | None):
    """查看笔记之间的 AI 关联。

    \b
    示例:
      brain connections                   # 列出全部关联
      brain connections -n a1b2c3d4e5f6  # 指定笔记的关联
    """
    _, metadata_store = _get_search_components()

    if note_id:
        # 查看特定笔记的关联
        note = metadata_store.get_note(note_id)
        if note is None:
            click.echo(f"❌ 笔记不存在: {note_id}")
            return

        conns = metadata_store.get_connections(note_id)
        click.echo(f"🔗 {note.title} 的关联 ({len(conns)} 条)\n")

        if not conns:
            click.echo("  暂无关联。")
            return

        for c in conns:
            # 判断当前笔记是 source 还是 target
            other_id = c.target_note_id if c.source_note_id == note_id else c.source_note_id
            other_note = metadata_store.get_note(other_id)
            other_title = other_note.title if other_note else other_id[:8]

            relation_icon = {
                "related": "🔗",
                "extends": "➡️",
                "contradicts": "⚡",
                "references": "📖",
            }.get(c.relation_type.value, "🔗")

            click.echo(f"  {relation_icon} [{c.relation_type.value}] → {other_title}")
            if c.description:
                click.echo(f"    {c.description}")
            click.echo(f"    强度: {c.strength:.0%}  |  id: {other_id}")
            click.echo()
    else:
        # 一次 SQL 取全部关联（含双端标题），替代逐篇 get_connections + get_note
        all_conns = metadata_store.get_all_connections_flat()

        click.echo(f"🔗 知识库关联 ({len(all_conns)} 条)\n")

        if not all_conns:
            click.echo("  暂无 AI 发现的关联。摄入更多同主题笔记后会自动发现。")
            return

        for c in all_conns:
            relation_type = c["relation_type"]
            relation_icon = {
                "related": "🔗",
                "extends": "➡️",
                "contradicts": "⚡",
                "references": "📖",
            }.get(relation_type, "🔗")

            src_title = c["source_title"] or c["source"][:8]
            tgt_title = c["target_title"] or c["target"][:8]
            description = c.get("description", "")
            strength = c["strength"]

            click.echo(f"  {relation_icon} [{relation_type}] {src_title}")
            click.echo(f"    → {tgt_title}")
            if description:
                click.echo(f"    {description}")
            click.echo(f"    强度: {strength:.0%}")
            click.echo()


# ============================================================
# brain digest — 每日/每周知识摘要
# ============================================================


@cli.command()
@click.option("--weekly", "-w", is_flag=True, help="生成本周趋势报告（默认每日简报）")
def digest(weekly: bool):
    """生成知识摘要。

    \b
    示例:
      brain digest           # 昨日知识简报
      brain digest --weekly  # 本周知识趋势
    """
    _, metadata_store = _get_search_components()

    from brain.services.digest import DigestService

    svc = DigestService(metadata_store)

    if weekly:
        click.echo("📊 生成每周趋势...")
        result = _run_async(svc.weekly())
    else:
        click.echo("📅 生成每日摘要...")
        result = _run_async(svc.daily())

    click.echo(f"\n{result}")


# ============================================================
# brain review — 复习提醒
# ============================================================


@cli.command()
@click.option("--limit", "-n", default=5, help="显示数量 (默认 5)")
def review(limit: int):
    """查看需要复习的旧笔记。

    \b
    示例:
      brain review
      brain review -n 10
    """
    _, metadata_store = _get_search_components()

    from brain.services.review import ReviewService

    svc = ReviewService(metadata_store)
    due = svc.get_due_items_sync(limit=limit)

    if not due:
        click.echo("✅ 暂无需要复习的内容。")
        return

    click.echo(f"📖 需要复习的笔记 ({len(due)} 条)\n")

    for i, item in enumerate(due, 1):
        title = item["title"]
        if item["is_new"]:
            status = "🆕"
            schedule = "首次进入复习"
        else:
            status = "🔁"
            schedule = (
                f"第 {item['review_count']} 次复习 | 间隔 {item['interval_days']} 天"
            )

        date_str = item.get("ingested_at", "")[:10] or "未知"
        click.echo(f"  {i}. {status} [{date_str}] {title}")
        click.echo(f"     {schedule}  |  下次: {item.get('due_date', '?')}")
        click.echo()


# ============================================================
# brain watch — 文件监听
# ============================================================


@cli.command()
@click.option("--dir", "-d", default=None, help="监听目录（默认配置的 notes_dir）")
def watch(dir: str):
    """监听目录，Markdown 文件变化自动摄入知识库。

    \b
    示例:
      brain watch                    # 监听默认目录
      brain watch -d ./my_notes      # 监听指定目录
      Ctrl+C 停止
    """
    from pathlib import Path

    from brain.ingestion.watcher import FileWatcher

    cfg = get_config()
    watch_dir = Path(dir) if dir else cfg.storage.notes_dir
    pipeline = _get_pipeline()

    watcher = FileWatcher(
        watch_dir=watch_dir,
        ingest_callback=lambda p: _record_ingest(watcher, pipeline, p),
        debounce_seconds=cfg.ingestion.debounce_seconds,
    )

    click.echo(f"👀 监听目录: {watch_dir}")
    click.echo("   放入/修改 .md 文件将自动摄入，Ctrl+C 停止")

    try:
        watcher.start()
        import time

        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        click.echo("\n停止监听")
        watcher.stop()


def _record_ingest(watcher, pipeline, file_path) -> None:
    """文件摄入回调——记录事件到 watcher。"""
    try:
        note_id = pipeline.ingest_file_sync(file_path)
        watcher.record_event(file_path.name, note_id)
        click.echo(f"✅ 已摄入: {file_path.name} → {note_id}")
    except Exception as e:
        click.echo(f"❌ 摄入失败: {file_path.name}: {e}")


# ============================================================
# brain rss — RSS 订阅管理
# ============================================================


@cli.group()
def rss():
    """RSS 订阅管理——拉取订阅源文章自动摄入知识库。"""


@rss.command("add")
@click.argument("url")
def rss_add(url: str):
    """添加 RSS 订阅源。"""
    pipeline = _get_pipeline()
    _, metadata_store = _get_search_components()

    from brain.ingestion.sources.rss import RssSource

    source = RssSource(pipeline, metadata_store)
    feed_id = source.add_feed(url)
    click.echo(f"✅ 已添加订阅源 #{feed_id}: {url}")


@rss.command("list")
def rss_list():
    """列出全部 RSS 订阅源。"""
    _, metadata_store = _get_search_components()


    # RssSource 只需要 metadata_store 就能列
    feeds = metadata_store.list_rss_feeds()
    if not feeds:
        click.echo("暂无订阅源。用 brain rss add <url> 添加")
        return

    for f in feeds:
        title = f["title"] or "(未拉取)"
        last = f["last_fetched_at"][:10] if f["last_fetched_at"] else "从未"
        click.echo(f"  #{f['id']} {f['url']}")
        click.echo(f"     标题: {title} | 累计摄入: {f['entry_count']} | 上次拉取: {last}")


@rss.command("fetch")
def rss_fetch():
    """立即拉取所有订阅源的新文章。"""
    pipeline = _get_pipeline()
    _, metadata_store = _get_search_components()

    from brain.ingestion.sources.rss import RssSource

    source = RssSource(pipeline, metadata_store)
    summary = source.fetch_all()
    click.echo(f"📡 检查 {summary['feeds_checked']} 个源，新增摄入 {summary['new_entries']} 条")
    for err in summary["errors"]:
        click.echo(f"  ❌ {err}")


@rss.command("remove")
@click.argument("feed_id", type=int)
def rss_remove(feed_id: int):
    """删除 RSS 订阅源。"""
    _, metadata_store = _get_search_components()
    ok = metadata_store.delete_rss_feed(feed_id)
    if ok:
        click.echo(f"✅ 已删除订阅源 #{feed_id}")
    else:
        click.echo(f"❌ 订阅源 #{feed_id} 不存在")


# ============================================================
# brain metrics — 可观测性指标
# ============================================================


@cli.command()
@click.option("--hours", "-h", default=24, help="统计时间窗口（小时，默认 24）")
@click.option("--traces", "-n", default=10, help="显示最近调用链数量（默认 10）")
def metrics(hours: int, traces: int):
    """查看可观测性指标（Phase 5A）。

    \b
    显示最近 N 小时的指标汇总和最近调用链。
    示例:
      brain metrics
      brain metrics -h 72      # 最近 3 天
      brain metrics -n 20      # 显示 20 条调用链
    """
    from brain.observability import check_health

    cfg = get_config()
    embedding_fn = get_embedding_fn()
    vector_store = VectorStore(persist_dir=cfg.storage.chroma_dir, embedding_fn=embedding_fn)
    metadata_store = MetadataStore(db_path=cfg.storage.db_path)
    metadata_store.initialize()

    # 健康检查
    health = check_health(metadata_store, vector_store, embedding_fn)
    click.echo("🏥 系统健康状态\n")
    for comp, status in health["components"].items():
        icon = "✅" if status == "ok" else ("⏭️" if status == "skipped" else "❌")
        click.echo(f"  {icon} {comp:12s} {status}")
    click.echo(f"  总体: {health['status']}\n")

    # 指标汇总
    summary = metadata_store.get_metrics_summary(hours=hours)
    click.echo(f"📊 最近 {hours} 小时指标\n")
    click.echo(f"  问答次数:     {summary['ask_count']}")
    click.echo(f"  平均问答延迟: {summary['avg_ask_latency_ms']} ms")
    click.echo(f"  工具调用次数: {summary['tool_call_count']}")
    click.echo(f"  LLM Token:    {summary['llm_token_total']}")
    click.echo(f"  摄入次数:     {summary['ingest_count']}")
    if summary['ingest_count']:
        click.echo(f"  平均摄入延迟: {summary['avg_ingest_latency_ms']} ms")

    # 最近调用链
    recent = metadata_store.get_recent_traces(limit=traces)
    if recent:
        click.echo(f"\n🔁 最近 {len(recent)} 条调用链\n")
        for t in recent:
            time_str = t["started_at"][11:19] if t["started_at"] else "?"
            click.echo(
                f"  [{time_str}] {t['trace_id']}  "
                f"耗时 {t['duration_ms']}ms  工具 {t['tool_calls']}次  "
                f"Token {t['tokens']}"
            )
    else:
        click.echo("\n  暂无调用链记录（进行一次问答后可观测）")


# ============================================================
# brain cost — 成本统计
# ============================================================


@cli.command()
@click.option("--hours", "-h", default=24, help="按模型统计的时间窗口（小时，默认 24）")
@click.option("--days", "-d", default=30, help="按日统计的天数（默认 30）")
def cost(hours: int, days: int):
    """查看 LLM 调用成本（Phase 5B）。

    \b
    显示今日/本月/总累计成本和配额用量。
    示例:
      brain cost
      brain cost -h 72      # 按模型看最近 3 天
      brain cost -d 7       # 按日看最近 7 天
    """
    from brain.config import get_config

    cfg = get_config()
    ms = MetadataStore(db_path=cfg.storage.db_path)
    ms.initialize()

    summary = ms.get_cost_summary()

    click.echo("💰 LLM 成本统计\n")
    click.echo(f"  今日: ¥{summary['today']['cost']:.4f} ({summary['today']['tokens']} token)")
    click.echo(f"  本月: ¥{summary['month']['cost']:.4f} ({summary['month']['tokens']} token)")
    click.echo(f"  总计: ¥{summary['total']['cost']:.4f} ({summary['total']['tokens']} token)")

    # 配额进度
    cost_cfg = cfg.cost
    click.echo("\n📋 配额用量")
    token_pct = summary['today']['tokens'] / cost_cfg.daily_token_limit * 100
    cost_pct = summary['today']['cost'] / cost_cfg.daily_cost_limit * 100
    click.echo(f"  日 token: {summary['today']['tokens']}/{cost_cfg.daily_token_limit} ({token_pct:.1f}%)")
    click.echo(f"  日成本:  ¥{summary['today']['cost']:.4f}/¥{cost_cfg.daily_cost_limit} ({cost_pct:.1f}%)")
    month_pct = summary['month']['tokens'] / cost_cfg.monthly_token_limit * 100
    click.echo(f"  月 token: {summary['month']['tokens']}/{cost_cfg.monthly_token_limit} ({month_pct:.1f}%)")

    # 按模型
    by_model = ms.get_cost_by_model(hours=hours)
    if by_model:
        click.echo(f"\n🏷️ 按模型（最近 {hours} 小时）\n")
        for m in by_model:
            click.echo(
                f"  {m['model']:20s} ¥{m['cost']:.4f}  "
                f"{m['total_tokens']} token ({m['calls']} 次)"
            )

    # 按日
    by_day = ms.get_cost_by_day(days=days)
    if by_day:
        click.echo(f"\n📅 按日（最近 {days} 天）\n")
        for d in by_day:
            click.echo(f"  {d['day']}  ¥{d['cost']:.4f}  {d['total_tokens']} token ({d['calls']} 次)")


# ============================================================
# brain eval — 离线评估
# ============================================================


@cli.command()
@click.option(
    "--dataset", "-d",
    default=None,
    help="Golden Dataset YAML 路径（默认从数据库加载）",
)
@click.option("--limit", "-n", default=None, type=int, help="只跑前 N 条（调试用）")
@click.option("--verbose", "-v", is_flag=True, help="显示每条用例详情")
def eval_cmd(dataset: str | None, limit: int | None, verbose: bool):
    """跑离线评估测试集（Phase 5D FR53）。

    \b
    对 Golden Dataset 逐条问答，规则打分（关键词+来源+完整性），
    生成通过率报告。改 prompt/换模型后跑此命令确认无退化。

    \b
    示例:
      brain eval                  # 从数据库加载用例
      brain eval -n 2             # 只跑前 2 条（调试）
      brain eval -v               # 显示详情
      brain eval -d custom.yaml   # 从 YAML 文件加载
    """
    from brain.embedding import get_embedding_fn
    from brain.eval.runner import EvalRunner
    from brain.storage.metadata import MetadataStore
    from brain.storage.vector_store import VectorStore

    cfg = get_config()
    vs = VectorStore(persist_dir=cfg.storage.chroma_dir, embedding_fn=get_embedding_fn())
    ms = MetadataStore(db_path=cfg.storage.db_path)
    ms.initialize()

    runner = EvalRunner(vs, ms)
    src = dataset or "数据库"
    click.echo(f"🧪 开始评估（dataset={src}）\n")
    report = runner.run(dataset, limit=limit)

    click.echo(report.summary())

    if verbose:
        click.echo("\n📋 全部用例详情\n")
        for r in report.results:
            status = "✅" if r.passed else "❌"
            click.echo(f"  {status} {r.case.id} [{r.case.question[:35]}]")
            click.echo(f"     得分 {r.score:.3f}（阈值 {r.case.min_score}）")
            if r.error:
                click.echo(f"     错误: {r.error}")
            else:
                hit = r.details.get("hit_keywords", [])
                miss = r.details.get("missed_keywords", [])
                click.echo(f"     命中关键词: {hit}")
                if miss:
                    click.echo(f"     未命中: {miss}")
            click.echo(f"     回答预览: {r.answer[:80]}...\n")

    # CI 模式：失败则退出码 1
    if report.failed > 0:
        raise click.ClickException(f"评估未通过：{report.failed} 条用例失败")


# ============================================================
# brain budget — 预算用量查询/重置
# ============================================================


@cli.command()
@click.option("--reset", is_flag=True, help="重置今日用量（清零计数器，不删历史记录）")
@click.option("--reset-month", is_flag=True, help="重置本月用量")
@click.option("--set-limit", type=int, default=None, help="临时设置日 token 配额（仅本次会话生效）")
def budget(reset: bool, reset_month: bool, set_limit: int | None):
    """查看或重置 token/成本预算用量。

    \b
    示例:
      brain budget              # 查看当前用量
      brain budget --reset      # 重置今日用量（不删历史记录）
      brain budget --reset-month  # 重置本月用量
    """
    from brain.config import get_config
    from brain.storage.metadata import MetadataStore

    cfg = get_config()
    store = MetadataStore(cfg.storage.db_path)
    store.initialize()

    if reset or reset_month:
        period = "today" if reset else "month"
        scope = "今日" if reset else "本月"
        # 只清零用量计数器，不删除 trace_events 历史调用记录
        store.reset_usage_counters(period)
        click.echo(f"✅ {scope}用量已重置（历史记录保留）")

    summary = store.get_cost_summary()
    click.echo("\n=== 预算用量 ===")
    click.echo(f"今日：{summary['today']['tokens']} token / ¥{summary['today']['cost']}")
    click.echo(f"本月：{summary['month']['tokens']} token / ¥{summary['month']['cost']}")
    click.echo(f"累计：{summary['total']['tokens']} token / ¥{summary['total']['cost']}")

    cost_cfg = cfg.cost
    click.echo(f"\n配额：日 {cost_cfg.daily_token_limit} token / ¥{cost_cfg.daily_cost_limit}，"
               f"月 {cost_cfg.monthly_token_limit} token")

    if set_limit is not None:
        cost_cfg.daily_token_limit = set_limit
        click.echo(f"\n⚠️  日 token 配额已临时设为 {set_limit}（仅本次进程生效）")
    store.close()


# ============================================================
# brain ui — 启动 Web 界面
# ============================================================


@cli.command()
@click.option("--port", "-p", default=7860, help="端口号 (默认 7860)")
@click.option("--host", "-h", default="127.0.0.1", help="绑定地址")
def ui(port: int, host: str):
    """启动 Web 界面（FastAPI + Vue）。

    \b
    示例:
      brain ui
      brain ui -p 8080
    """
    import uvicorn

    click.echo(f"🧠 Brain API 启动: http://{host}:{port}")
    click.echo(f"📖 API 文档: http://{host}:{port}/docs")
    uvicorn.run(
        "brain.api.server:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
    )


# ============================================================
# 入口
# ============================================================


def main():
    """CLI 入口函数。"""
    try:
        cli()
    finally:
        # ChromaDB / sentence-transformers 的非 daemon 线程会阻止进程退出，
        # 用 os._exit 强制退出（CLI 命令执行完后不涉及数据丢失风险）
        os._exit(0)


if __name__ == "__main__":
    main()
