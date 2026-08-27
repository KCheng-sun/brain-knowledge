"""可观测性基础设施（Phase 5A）。

提供：
  - trace_id 的生成与上下文透传（contextvars）
  - 健康检查（探测 LLM/Embedding/SQLite/ChromaDB 连通性）
  - 指标记录的统一入口（薄封装 MetadataStore.record_metric）

设计原则：本地优先，轻量实现。
不引入 Prometheus/ELK，指标存 SQLite，日志用 loguru JSON sink。
"""

import contextvars
import time
import uuid
from datetime import datetime
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from loguru import logger

# ============================================================
# Trace ID 上下文透传
# ============================================================

# contextvars 保证 trace_id 在异步调用链中正确透传，
# 不会因线程/协程切换而丢失（比全局变量安全）。
_trace_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "trace_id", default=None
)


def new_trace_id() -> str:
    """生成新的 trace_id（UUID4 短格式，与 note_id 风格一致）。"""
    return uuid.uuid4().hex[:12]


def set_trace_id(trace_id: str | None) -> contextvars.Token:
    """设置当前上下文的 trace_id。返回 token 用于恢复。"""
    token = _trace_id_var.set(trace_id)
    if trace_id:
        logger.bind(trace_id=trace_id).info(f"trace 开始: {trace_id}")
    return token


def get_trace_id() -> str | None:
    """获取当前上下文的 trace_id。"""
    return _trace_id_var.get()


def reset_trace_id(token: contextvars.Token) -> None:
    """恢复 trace_id 到设置前的状态。

    注意：contextvars.Token.reset() 要求在创建 token 的同一 context 中调用，
    否则抛 ValueError。Starlette 的 iterate_in_threadpool 会对同步生成器的
    每次 next() 创建新 context，导致跨 context reset 失败。
    因此本函数对跨 context 异常做容错处理（静默忽略），实际项目中应优先
    在 record_metric 显式传 trace_id，避免依赖 contextvar 透传。
    """
    try:
        _trace_id_var.reset(token)
    except ValueError:
        # token 创建于不同 context（如 threadpool 场景），无法 reset，静默忽略
        # contextvar 会随 context 回收自动消失，不影响正确性
        pass


# ============================================================
# 指标记录（薄封装，避免业务代码直接依赖 MetadataStore）
# ============================================================


def record_metric(
    metadata_store,
    metric_type: str,
    metric_name: str,
    value: float,
    metadata: dict[str, Any] | None = None,
    trace_id: str | None = None,
) -> None:
    """记录一条指标。

    trace_id 默认取当前上下文，调用方无需显式传递。
    指标记录失败不抛异常（可观测性不能影响主流程）。

    Args:
        metadata_store: MetadataStore 实例
        metric_type: 'ask' | 'ingest' | 'tool_call' | 'llm_call'
        metric_name: 'latency_ms' | 'token_count' | 'count' 等
        value: 指标值
        metadata: 附加信息
        trace_id: 显式指定 trace_id（默认取上下文）
    """
    tid = trace_id or get_trace_id()
    try:
        metadata_store.record_metric(
            metric_type=metric_type,
            metric_name=metric_name,
            value=value,
            trace_id=tid,
            metadata=metadata,
        )
    except Exception as e:
        # 指标记录失败不应影响主流程，仅记录警告
        logger.warning(f"指标记录失败 ({metric_type}/{metric_name}): {e}")


class MetricsTimer:
    """计时器上下文管理器，结束时自动记录 latency_ms 指标。

    用法:
        with MetricsTimer(ms, "ask", "latency_ms"):
            # 执行问答逻辑
            ...

    或手动控制:
        timer = MetricsTimer(ms, "ingest", "latency_ms")
        timer.start()
        ...
        timer.stop()
    """

    def __init__(
        self,
        metadata_store,
        metric_type: str,
        metric_name: str = "latency_ms",
        metadata: dict[str, Any] | None = None,
        trace_id: str | None = None,
    ):
        self._ms = metadata_store
        self._metric_type = metric_type
        self._metric_name = metric_name
        self._metadata = metadata
        # 显式 trace_id 优先；为 None 时 record_metric 回退到上下文（可能不可靠）
        self._trace_id = trace_id
        self._start: float | None = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        return False  # 不吞异常

    def start(self) -> None:
        self._start = time.perf_counter()

    def stop(self) -> float:
        """停止计时并记录。返回耗时毫秒数。"""
        if self._start is None:
            return 0.0
        elapsed_ms = (time.perf_counter() - self._start) * 1000
        meta = dict(self._metadata or {})
        if exc_info := _current_exception():
            meta["error"] = exc_info
        record_metric(
            self._ms,
            self._metric_type,
            self._metric_name,
            round(elapsed_ms, 1),
            meta,
            trace_id=self._trace_id,
        )
        self._start = None
        return elapsed_ms


def _current_exception() -> str | None:
    """获取当前上下文中的异常信息（用于 __exit__ 时记录错误）。"""
    import sys

    exc = sys.exc_info()[1]
    if exc:
        return f"{type(exc).__name__}: {exc}"
    return None


# ============================================================
# 健康检查
# ============================================================


def check_health(metadata_store, vector_store, embedding_fn=None) -> dict:
    """检查各组件健康状态。

    LLM/Embedding 探测用最小调用，避免消耗配额：
      - SQLite: 一次 SELECT
      - ChromaDB: count()
      - Embedding: 对空字符串做 1 次 embedding（如有 fn）
      - LLM: 跳过（dry_run 时探测，否则标记 skipped 避免烧钱）

    Returns:
        {
            "status": "healthy" | "degraded" | "unhealthy",
            "components": {sqlite, chromadb, embedding, llm},
            "timestamp": str
        }
    """
    components: dict[str, str] = {}
    now = datetime.now().isoformat()

    # SQLite
    try:
        metadata_store.count_notes()
        components["sqlite"] = "ok"
    except Exception as e:
        components["sqlite"] = f"error: {e}"
        logger.warning(f"健康检查 SQLite 失败: {e}")

    # ChromaDB
    try:
        vector_store.count()
        components["chromadb"] = "ok"
    except Exception as e:
        components["chromadb"] = f"error: {e}"
        logger.warning(f"健康检查 ChromaDB 失败: {e}")

    # Embedding（探测用空字符串，不消耗有意义配额）
    if embedding_fn is None:
        components["embedding"] = "skipped"
    else:
        try:
            embedding_fn(["ping"])
            components["embedding"] = "ok"
        except Exception as e:
            components["embedding"] = f"error: {e}"
            logger.warning(f"健康检查 Embedding 失败: {e}")

    # LLM 探测：dry_run 才真调，否则标记 skipped（避免烧配额）
    from brain.config import get_config

    cfg = get_config()
    if cfg.dry_run:
        components["llm"] = "ok"
    else:
        components["llm"] = "skipped"

    # 总体状态：任一 error 即 degraded（embedding/llm skipped 不算 degraded）
    error_count = sum(1 for v in components.values() if v.startswith("error"))
    if error_count == 0:
        status = "healthy"
    elif error_count >= 2:
        status = "unhealthy"
    else:
        status = "degraded"

    return {
        "status": status,
        "components": components,
        "timestamp": now,
    }


# ============================================================
# 调用链事件记录回调（LLM 请求响应 + 工具入参出参）
# ============================================================


def _messages_to_text(messages) -> str:
    """把 LangChain messages 列表转为可读文本（截断到合理长度）。"""
    parts = []
    for msg_list in messages:
        # messages 可能是 list[list[BaseMessage]] 或 list[BaseMessage]
        msgs = msg_list if isinstance(msg_list, (list, tuple)) else [msg_list]
        for m in msgs:
            role = getattr(m, "type", m.__class__.__name__)
            content = getattr(m, "content", "")
            if content:
                # 单条消息截断 2000 字符，避免超长 prompt 撑爆数据库
                text = content if len(content) <= 2000 else content[:2000] + "...(截断)"
                parts.append(f"[{role}] {text}")
    return "\n".join(parts)


def _extract_token_usage(response) -> tuple[int, int, int, str, int]:
    """从 LLMResult 提取 (prompt, completion, total, model_name, cache_hit)。

    cache_hit 为缓存命中的 input token 数（DeepSeek 返回在 input_token_details 里）。
    """
    prompt_tokens = completion_tokens = cache_hit = 0
    llm_output = getattr(response, "llm_output", None) or {}
    token_usage = llm_output.get("token_usage", {}) or llm_output.get("usage", {})
    if token_usage:
        prompt_tokens = token_usage.get("prompt_tokens", 0)
        completion_tokens = token_usage.get("completion_tokens", 0)
        # 缓存命中（OpenAI 格式）
        pd = token_usage.get("prompt_tokens_details") or {}
        cache_hit = pd.get("cached_tokens", 0)

    model_name = llm_output.get("model_name", "")
    if not prompt_tokens and not completion_tokens:
        for gen in getattr(response, "generations", []):
            for g in gen:
                msg = getattr(g, "message", None)
                if msg:
                    um = getattr(msg, "usage_metadata", None)
                    if um:
                        prompt_tokens = um.get("input_tokens", 0)
                        completion_tokens = um.get("output_tokens", 0)
                        # 缓存命中（LangChain usage_metadata 格式）
                        itd = um.get("input_token_details") or {}
                        cache_hit = itd.get("cache_read", 0) or itd.get("cached", 0)
                    if not model_name:
                        rmeta = getattr(msg, "response_metadata", {}) or {}
                        model_name = rmeta.get("model_name", "") or rmeta.get("model", "")
                    if prompt_tokens or completion_tokens:
                        break
            if prompt_tokens or completion_tokens:
                break
    return prompt_tokens, completion_tokens, prompt_tokens + completion_tokens, model_name, cache_hit


# ============================================================
# Token 成本计价（Phase 5B FR47）
# ============================================================

# 内置模型价格表（¥/1M token，DeepSeek 官方定价 2025-08）
# 分空闲/高峰时段，且区分缓存命中/未命中。
# cache_hit: 缓存命中价（便宜约 30 倍）
# cache_miss: 缓存未命中价（即常规价）
# 每档又分 idle（空闲）/ peak（高峰，约 2 倍）
MODEL_PRICING: dict[str, dict] = {
    "deepseek-v4-flash": {
        "input": {"idle": {"cache_hit": 0.05, "cache_miss": 1.5},
                 "peak": {"cache_hit": 0.10, "cache_miss": 3.0}},
        "output": {"idle": 4.5, "peak": 9.0},
    },
    "deepseek-v4-pro": {
        "input": {"idle": {"cache_hit": 0.15, "cache_miss": 4.5},
                 "peak": {"cache_hit": 0.30, "cache_miss": 9.0}},
        "output": {"idle": 13.5, "peak": 27.0},
    },
    "deepseek-v4-flash-vision-exp": {
        "input": {"idle": {"cache_hit": 0.05, "cache_miss": 1.5},
                 "peak": {"cache_hit": 0.10, "cache_miss": 3.0}},
        "output": {"idle": 4.5, "peak": 9.0},
    },
    # 旧型号兼容（已在生产使用的别名）
    "deepseek-chat": {"_alias": "deepseek-v4-flash"},
    "deepseek-reasoner": {"_alias": "deepseek-v4-flash"},
    # Anthropic（备选）
    "claude-3-5-sonnet": {
        "input": {"idle": {"cache_hit": 22.0, "cache_miss": 22.0},
                 "peak": {"cache_hit": 22.0, "cache_miss": 22.0}},
        "output": {"idle": 110.0, "peak": 110.0},
    },
    "claude-3-5-haiku": {
        "input": {"idle": {"cache_hit": 5.5, "cache_miss": 5.5},
                 "peak": {"cache_hit": 5.5, "cache_miss": 5.5}},
        "output": {"idle": 27.5, "peak": 27.5},
    },
}


def _resolve_pricing(model: str) -> dict:
    """解析模型价格，处理别名。"""
    p = MODEL_PRICING.get(model)
    if p is None:
        # 未知模型默认用 v4-flash 价
        return MODEL_PRICING["deepseek-v4-flash"]
    if "_alias" in p:
        return MODEL_PRICING[p["_alias"]]
    return p


def calc_token_cost(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    *,
    peak_hours: bool = False,
    cache_hit_tokens: int = 0,
) -> float:
    """计算单次 LLM 调用成本（¥）。

    Args:
        model: 模型名
        prompt_tokens: 输入 token 总数
        completion_tokens: 输出 token 数
        peak_hours: 是否高峰时段（默认空闲）
        cache_hit_tokens: 缓存命中的 prompt token 数（默认 0=全部未命中）

    Returns:
        成本（人民币元，保留 6 位小数）
    """
    pricing = _resolve_pricing(model)
    period = "peak" if peak_hours else "idle"

    # 输入分缓存命中/未命中两部分计价
    cache_miss_tokens = max(0, prompt_tokens - cache_hit_tokens)
    input_pricing = pricing["input"][period]
    input_cost = (
        cache_hit_tokens / 1_000_000 * input_pricing["cache_hit"]
        + cache_miss_tokens / 1_000_000 * input_pricing["cache_miss"]
    )
    output_cost = completion_tokens / 1_000_000 * pricing["output"][period]
    return round(input_cost + output_cost, 6)


def _extract_response_text(response) -> str:
    """从 LLMResult 提取响应文本（拼接所有 generation 的 content）。"""
    parts = []
    for gen in getattr(response, "generations", []):
        for g in gen:
            msg = getattr(g, "message", None)
            text = getattr(msg, "content", None) or getattr(g, "text", None)
            if text:
                parts.append(text)
    result = "\n".join(parts)
    return result if len(result) <= 2000 else result[:2000] + "...(截断)"


def check_budget(metadata_store) -> dict:
    """检查当前是否超出 token/成本配额（Phase 5B FR48）。

    Returns:
        {
            "ok": bool,              # 是否未超限
            "reason": str,           # 超限原因（ok=True 时为空）
            "today": {tokens, cost}, # 今日用量
            "limits": {daily_token, monthly_token, daily_cost}
        }
    """
    from brain.config import get_config

    cfg = get_config()
    cost_cfg = cfg.cost
    summary = metadata_store.get_cost_summary()

    today_tokens = summary["today"]["tokens"]
    today_cost = summary["today"]["cost"]
    month_tokens = summary["month"]["tokens"]

    limits = {
        "daily_token": cost_cfg.daily_token_limit,
        "monthly_token": cost_cfg.monthly_token_limit,
        "daily_cost": cost_cfg.daily_cost_limit,
    }

    if today_tokens >= cost_cfg.daily_token_limit:
        return {
            "ok": False,
            "reason": f"日 token 配额已用尽（{today_tokens}/{cost_cfg.daily_token_limit}）",
            "today": summary["today"],
            "limits": limits,
        }
    if month_tokens >= cost_cfg.monthly_token_limit:
        return {
            "ok": False,
            "reason": f"月 token 配额已用尽（{month_tokens}/{cost_cfg.monthly_token_limit}）",
            "today": summary["today"],
            "limits": limits,
        }
    if today_cost >= cost_cfg.daily_cost_limit:
        return {
            "ok": False,
            "reason": f"日成本上限已用尽（¥{today_cost:.4f}/{cost_cfg.daily_cost_limit}）",
            "today": summary["today"],
            "limits": limits,
        }

    return {"ok": True, "reason": "", "today": summary["today"], "limits": limits}


class TraceEventLogger(BaseCallbackHandler):
    """LangChain 回调：记录完整调用链事件 + LLM token。

    同时写入两张表：
      - metrics 表：llm_call/token_count（用于看板统计）
      - trace_events 表：每轮 LLM/工具的完整入参出参（用于调用链回放）

    事件序列（一次 LLM 调用）：
      on_chat_model_start → 记录 llm_start（请求 prompt）
      on_llm_end          → 记录 llm_end（响应文本 + token + latency）
    事件序列（一次工具调用）：
      on_tool_start → 记录 tool_start（入参）
      on_tool_end   → 记录 tool_end（出参 + latency）

    用法::

        logger = TraceEventLogger(ms, trace_id)
        agent.stream(..., config={"callbacks": [logger]})
    """

    def __init__(self, metadata_store, trace_id: str | None = None):
        self._ms = metadata_store
        self._trace_id = trace_id
        # 暂存每次调用的起始时间，用于计算 latency
        self._llm_starts: dict[str, float] = {}  # run_id -> perf_counter
        self._tool_starts: dict[str, float] = {}

    def on_chat_model_start(self, serialized, messages, *, run_id=None, **kwargs):
        """LLM 调用开始：记录请求 prompt。"""
        import time

        self._llm_starts[str(run_id)] = time.perf_counter()
        if self._trace_id:
            model_name = serialized.get("name", "") if isinstance(serialized, dict) else ""
            prompt_text = _messages_to_text(messages)
            self._ms.add_trace_event(
                self._trace_id, "llm_start",
                name=model_name,
                input_data=prompt_text,
                run_id=str(run_id),
            )

    def on_llm_end(self, response, *, run_id=None, **kwargs):
        """LLM 调用结束：记录响应文本 + token + latency，并写入 metrics 表。"""
        import time

        prompt_t, completion_t, total_t, model_name, cache_hit = _extract_token_usage(response)
        response_text = _extract_response_text(response)
        start = self._llm_starts.pop(str(run_id), None)
        latency = round((time.perf_counter() - start) * 1000, 1) if start else None

        # 写 trace_events（完整响应）
        if self._trace_id:
            token_usage = None
            if total_t > 0:
                token_usage = {
                    "prompt": prompt_t,
                    "completion": completion_t,
                    "total": total_t,
                    "cache_hit": cache_hit,
                    "cost": calc_token_cost(
                        model_name, prompt_t, completion_t, cache_hit_tokens=cache_hit
                    ),
                }
            self._ms.add_trace_event(
                self._trace_id, "llm_end",
                name=model_name,
                output=response_text,
                token_usage=token_usage,
                latency_ms=latency,
                run_id=str(run_id),
            )

        # 写 metrics（token 统计，供看板聚合）
        if total_t > 0:
            record_metric(
                self._ms, "llm_call", "token_count", total_t,
                {"prompt_tokens": prompt_t, "completion_tokens": completion_t, "model": model_name},
                trace_id=self._trace_id,
            )
            logger.debug(
                f"LLM token 统计: prompt={prompt_t}, completion={completion_t}, total={total_t}"
            )

    def on_tool_start(self, serialized, input_str, *, run_id=None, inputs=None, **kwargs):
        """工具调用开始：记录入参。"""
        import time

        self._tool_starts[str(run_id)] = time.perf_counter()
        if self._trace_id:
            tool_name = ""
            if isinstance(serialized, dict):
                tool_name = serialized.get("name", "")
            if not tool_name and inputs:
                tool_name = inputs.get("name", "")
            # inputs 比 input_str 结构更清晰，优先用
            input_data = None
            if inputs:
                import json

                input_data = json.dumps(inputs, ensure_ascii=False, default=str)[:2000]
            elif input_str:
                input_data = input_str[:2000]
            self._ms.add_trace_event(
                self._trace_id, "tool_start",
                name=tool_name,
                input_data=input_data,
                run_id=str(run_id),
            )

    def on_tool_end(self, output, *, run_id=None, **kwargs):
        """工具调用结束：记录出参 + latency。"""
        import time

        start = self._tool_starts.pop(str(run_id), None)
        latency = round((time.perf_counter() - start) * 1000, 1) if start else None
        if self._trace_id:
            output_str = str(output)
            if len(output_str) > 2000:
                output_str = output_str[:2000] + "...(截断)"
            self._ms.add_trace_event(
                self._trace_id, "tool_end",
                output=output_str,
                latency_ms=latency,
                run_id=str(run_id),
            )


# 向后兼容别名（旧代码可能 import TokenTrackingCallback）
TokenTrackingCallback = TraceEventLogger
