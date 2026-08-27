"""定时任务调度器 — 轻量后台线程实现。

不用 APScheduler，自写分钟级检查循环足够：
  - RSS 自动拉取: 每 60 分钟
  - 每日摘要: 每天 08:00（生成昨日简报并存库）
  - 每周趋势: 每周一 09:00（生成本周趋势并存库）

任务状态（上次运行时间/结果/下次运行时间）存内存，
供 API /api/scheduler/status 查询。
"""

import threading
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta

from loguru import logger


class ScheduledTask:
    """单个定时任务的定义和状态。"""

    def __init__(
        self,
        name: str,
        interval_minutes: int,
        run_at_hour: int,
        run_at_weekday: int | None,  # None = 每天；0=周一 ... 6=周日
        func: Callable[[], str],
        description: str,
    ):
        self.name = name
        self.interval_minutes = interval_minutes
        self.run_at_hour = run_at_hour
        self.run_at_weekday = run_at_weekday
        self.func = func
        self.description = description
        self.last_run_at: datetime | None = None
        self.last_result: str = ""
        self.next_run_at: datetime | None = None
        self.run_count = 0
        self._lock = threading.Lock()

    def is_due(self, now: datetime) -> bool:
        """判断任务是否到期。"""
        if self.last_run_at is None:
            # 首次运行：已过执行时刻则立即运行
            due = now.hour >= self.run_at_hour
            if self.run_at_weekday is not None:
                due = due and now.weekday() == self.run_at_weekday
            return due
        # 按固定间隔检查
        return (now - self.last_run_at) >= timedelta(minutes=self.interval_minutes)

    def compute_next_run(self, now: datetime) -> datetime:
        """计算下次运行时间（展示用）。"""
        next_run = now + timedelta(minutes=self.interval_minutes)
        if self.run_at_weekday is None:
            # 每天固定时刻
            next_run = next_run.replace(hour=self.run_at_hour, minute=0, second=0, microsecond=0)
            if next_run <= now:
                next_run += timedelta(days=1)
        else:
            # 每周固定时刻
            days_ahead = (self.run_at_weekday - now.weekday()) % 7
            next_run = (now + timedelta(days=days_ahead)).replace(
                hour=self.run_at_hour, minute=0, second=0, microsecond=0
            )
            if next_run <= now:
                next_run += timedelta(days=7)
        return next_run

    def run(self) -> str:
        """执行任务并记录状态。"""
        with self._lock:
            self.last_run_at = datetime.now()
            try:
                result = self.func()
                self.last_result = f"✅ {result}"
                self.run_count += 1
            except Exception as e:
                self.last_result = f"❌ {e}"
                logger.error(f"[scheduler] 任务 {self.name} 失败: {e}")
            self.next_run_at = self.compute_next_run(datetime.now())
            return self.last_result


class TaskScheduler:
    """后台调度线程 — 每 30 秒检查一次任务到期。"""

    def __init__(self, check_interval_seconds: int = 30):
        self._tasks: list[ScheduledTask] = []
        self._check_interval = check_interval_seconds
        self._stop = False
        self._thread: threading.Thread | None = None

    def add_task(self, task: ScheduledTask) -> None:
        task.next_run_at = task.compute_next_run(datetime.now())
        self._tasks.append(task)
        logger.info(f"[scheduler] 注册任务: {task.name} — {task.description}")

    def start(self) -> None:
        """启动调度线程（非阻塞）。"""
        self._thread = threading.Thread(target=self._loop, daemon=True, name="task-scheduler")
        self._thread.start()
        logger.info("[scheduler] 调度器已启动")

    def stop(self) -> None:
        self._stop = True

    def _loop(self) -> None:
        while not self._stop:
            now = datetime.now()
            for task in self._tasks:
                try:
                    if task.is_due(now):
                        result = task.run()
                        logger.info(f"[scheduler] {task.name}: {result}")
                except Exception as e:
                    logger.error(f"[scheduler] 检查任务 {task.name} 时出错: {e}")
            time.sleep(self._check_interval)

    def get_status(self) -> list[dict]:
        """获取全部任务状态。"""
        return [
            {
                "name": t.name,
                "description": t.description,
                "last_run_at": t.last_run_at.isoformat() if t.last_run_at else None,
                "last_result": t.last_result,
                "next_run_at": t.next_run_at.isoformat() if t.next_run_at else None,
                "run_count": t.run_count,
            }
            for t in self._tasks
        ]

    def run_now(self, name: str) -> str | None:
        """手动立即执行某任务。"""
        for task in self._tasks:
            if task.name == name:
                return task.run()
        return None


# ============================================================
# 构建默认调度器
# ============================================================


def build_default_scheduler(pipeline, metadata_store, vector_store) -> TaskScheduler:
    """构建默认任务集。"""
    from brain.ingestion.sources.rss import RssSource
    from brain.services.digest import DigestService

    rss_source = RssSource(pipeline, metadata_store)
    digest_service = DigestService(metadata_store)

    scheduler = TaskScheduler()

    # 任务 1: RSS 自动拉取（每 60 分钟）
    def _rss_sync() -> str:
        feeds = metadata_store.list_rss_feeds()
        if not feeds:
            return "无订阅源，跳过"
        summary = rss_source.fetch_all()
        return f"检查 {summary['feeds_checked']} 个源，新增 {summary['new_entries']} 条"

    scheduler.add_task(
        ScheduledTask(
            name="rss_sync",
            interval_minutes=60,
            run_at_hour=0,  # 间隔任务不看时刻
            run_at_weekday=None,
            func=_rss_sync,
            description="RSS 订阅自动拉取（每 60 分钟）",
        )
    )

    # 任务 2: 每日摘要（每天 08:00，生成昨日简报）
    def _daily_digest() -> str:
        target = date.today() - timedelta(days=1)
        content = digest_service.daily_sync(target_date=target)
        metadata_store.save_digest_report("daily", target.isoformat(), content)
        return f"已生成 {target.isoformat()} 每日摘要"

    scheduler.add_task(
        ScheduledTask(
            name="daily_digest",
            interval_minutes=24 * 60,
            run_at_hour=8,
            run_at_weekday=None,
            func=_daily_digest,
            description="每日摘要（每天 08:00）",
        )
    )

    # 任务 3: 每周趋势（每周一 09:00）
    def _weekly_digest() -> str:
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        content = digest_service.weekly_sync()
        metadata_store.save_digest_report("weekly", monday.isoformat(), content)
        return f"已生成 {monday.isoformat()} 每周趋势"

    scheduler.add_task(
        ScheduledTask(
            name="weekly_digest",
            interval_minutes=7 * 24 * 60,
            run_at_hour=9,
            run_at_weekday=0,  # 周一
            func=_weekly_digest,
            description="每周趋势（周一 09:00）",
        )
    )

    # Phase 5D FR55：每周 LLM-as-Judge 抽样评估
    def _weekly_eval() -> str:
        from brain.eval.judge import LLMJudge

        judge = LLMJudge(metadata_store)
        results = judge.judge_recent_traces(sample_rate=0.1, limit=10)
        if not results:
            return "无可用 trace，跳过评估"
        avg = sum(r.get("score", 0) for r in results) / len(results)
        return f"已评估 {len(results)} 条，平均分 {avg:.1f}/5"

    scheduler.add_task(
        ScheduledTask(
            name="weekly_eval",
            interval_minutes=7 * 24 * 60,
            run_at_hour=10,
            run_at_weekday=0,  # 周一 10:00
            func=_weekly_eval,
            description="每周 LLM-as-Judge 抽样（周一 10:00）",
        )
    )

    return scheduler
