"""每日摘要服务。

从 prompts 表读取提示词模板（daily_digest/weekly_trend），
将昨日/本周的笔记整理为结构化摘要。
"""

from datetime import date, timedelta

from loguru import logger

from brain.llm import get_chat_model
from brain.prompts import get_prompt_template
from brain.storage.metadata import MetadataStore


class DigestService:
    """摘要服务 — 生成每日简报和每周趋势分析。"""

    def __init__(self, metadata_store: MetadataStore):
        self._store = metadata_store

    def daily_sync(self, target_date: date | None = None) -> str:
        if target_date is None:
            target_date = date.today() - timedelta(days=1)
        return self._generate(target_date=target_date, days_range=1,
                              prompt_key="daily_digest",
                              title_date=target_date.isoformat())

    def weekly_sync(self) -> str:
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        return self._generate(target_date=monday, days_range=7,
                              prompt_key="weekly_trend",
                              title_date=f"{monday.isoformat()} ~ {today.isoformat()}")

    async def daily(self, target_date: date | None = None) -> str:
        """生成指定日期的知识简报。默认昨天。

        Returns:
            Markdown 格式的摘要字符串
        """
        if target_date is None:
            target_date = date.today() - timedelta(days=1)

        logger.info(f"生成每日摘要: {target_date}")
        return self._generate(
            target_date=target_date,
            days_range=1,
            prompt_key="daily_digest",
            title_date=target_date.isoformat(),
        )

    async def weekly(self) -> str:
        """生成本周知识趋势分析。

        Returns:
            Markdown 格式的趋势报告
        """
        today = date.today()
        monday = today - timedelta(days=today.weekday())

        logger.info(f"生成每周趋势: {monday} ~ {today}")
        return self._generate(
            target_date=monday,
            days_range=7,
            prompt_key="weekly_trend",
            title_date=f"{monday.isoformat()} ~ {today.isoformat()}",
        )

    def _generate(
        self,
        target_date: date,
        days_range: int,
        prompt_key: str,
        title_date: str,
    ) -> str:
        """核心生成逻辑。"""
        # 1. 收集时间范围内的笔记
        all_notes = self._store.list_notes(limit=10000)

        start_date = target_date
        end_date = target_date + timedelta(days=days_range)

        range_notes = [
            n
            for n in all_notes
            if n.ingested_at
            and start_date.isoformat() <= n.ingested_at[:10] <= end_date.isoformat()
        ]

        if not range_notes:
            if days_range == 1:
                return f"### 📅 {title_date} 知识简报\n\n昨日没有摄入新笔记。"
            else:
                return f"### 📊 {title_date} 知识趋势\n\n本周没有摄入新笔记。"

        # 2. 收集标签和关联
        all_tags: dict[str, int] = {}
        total_conns = 0
        connection_descriptions: list[str] = []

        for note in range_notes:
            tags = self._store.get_note_tags(note.id)
            for t in tags:
                all_tags[t.name] = all_tags.get(t.name, 0) + 1

            conns = self._store.get_connections(note.id)
            total_conns += len(conns)
            for c in conns:
                if c.description:
                    connection_descriptions.append(c.description)

        # 3. 组装 prompt
        notes_section = "\n".join(
            f"- [{n.ingested_at[:10] if n.ingested_at else '?'}] {n.title}"
            for n in range_notes
        )

        tags_section = (
            "\n".join(f"- {name} (×{count})" for name, count in sorted(all_tags.items(), key=lambda x: x[1], reverse=True))
            if all_tags
            else "无"
        )

        conns_section = (
            "\n".join(f"- {desc}" for desc in connection_descriptions[:5])
            if connection_descriptions
            else "无"
        )

        tag_stats = (
            "\n".join(
                f"- {name}: {count} 篇"
                for name, count in sorted(all_tags.items(), key=lambda x: x[1], reverse=True)[:10]
            )
            if all_tags
            else "无"
        )

        # 4. LLM 生成
        llm = get_chat_model()

        # Phase 5G：Langfuse 追踪摘要生成（直接 LLM 调用，用上下文管理器建 trace）
        from brain.langfuse_tracing import langfuse_trace
        trace_name = "daily-digest" if days_range == 1 else "weekly-trend"

        if days_range == 1:
            prompt = get_prompt_template(
                prompt_key,
                notes_section=notes_section,
                tags_section=tags_section,
                connections_section=conns_section,
                date_str=title_date,
            )
            with langfuse_trace(trace_name, tags=["digest"]) as lf:
                response = llm.invoke(prompt, config=lf.langchain_config())
            return response.content
        else:
            prompt = get_prompt_template(
                prompt_key,
                notes_section=notes_section,
                tags_stats=tag_stats,
                connection_count=total_conns // 2,
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat(),
            )
            with langfuse_trace(trace_name, tags=["digest"]) as lf:
                response = llm.invoke(prompt, config=lf.langchain_config())
            return response.content
