"""Langfuse 追踪集成（Phase 5G）。

提供 Langfuse 追踪的统一入口，遵循 Langfuse 最佳实践：

1. **懒加载 + 环境变量优先**：Langfuse 客户端在首次进入 trace 上下文时才初始化，
   且必须在 .env / 环境变量加载之后（config.get_config() 已确保 .env 加载）。
2. **无凭证/禁用时降级**：未配置凭证或 tracing_enabled=False 时，所有入口返回
   原样 config / Noop 上下文，主流程零影响（可观测性不能影响主流程，与 record_metric 一致）。
3. **session_id 透传**：session_id 作为 Langfuse session_id，同会话多轮问答在
   Langfuse Sessions 视图按顺序串联。应用 trace_id 存入 metadata.brain_trace_id 供互查。
4. **环境隔离**：environment 属性区分 development/staging/production，避免测试 trace
   污染生产看板。

Langfuse v4 SDK 关键导入（与 v2/v3 不兼容，已按 v4 文档实现）：
  - from langfuse import get_client, propagate_attributes
  - from langfuse.langchain import CallbackHandler

两个入口（按调用路径选）：
  - **attach_langfuse(config, ...)**：给 agent / chain 调用（agent.stream/invoke、
    BaseAgent.run）。这些路径会触发 LangChain on_chain_start，CallbackHandler 从
    config.metadata 的 langfuse_* 前缀自动解析 trace 属性（v4 文档 Option 1）。
  - **langfuse_trace(...) 上下文管理器**：给直接 LLM 调用（digest/query_rewriter/judge
    等 llm.invoke(messages)）。直接 LLM 调用只触发 on_chat_model_start，不解析
    config.metadata，必须用 start_as_current_observation 建 trace root +
    propagate_attributes 设属性，CallbackHandler 在上下文内继承当前 trace。

踩坑总结（实现依据）：
  - 直接 llm.invoke() 只触发 on_chat_model_start，CallbackHandler 不从 config.metadata
    解析 langfuse_* 属性（trace_name 退化为模型名、session_id/tags 丢失）。
  - trace_context 是「连接已存在 trace」的路径，会跳过 metadata 属性解析，互斥，不可用。
  - 文档：https://langfuse.com/docs/integrations/langchain/tracing
    https://langfuse.com/docs/observability/best-practices
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from loguru import logger


def is_enabled() -> bool:
    """Langfuse 追踪是否启用。

    启用条件：配置开关为 True 且环境变量中存在 PUBLIC_KEY（有凭证才会真连）。
    测试环境（无 .env 的凭证）会自动返回 False，不初始化客户端。
    """
    from brain.config import get_config

    cfg = get_config()
    if not cfg.langfuse.tracing_enabled:
        return False
    # 凭证缺失时不启用——get_client() 会打印 disabled 警告并静默丢弃事件，
    # 提前判定可避免无谓的上下文对象和反复告警
    return bool(os.environ.get("LANGFUSE_PUBLIC_KEY"))


def attach_langfuse(
    config: dict | None,
    *,
    session_id: str | None = None,
    trace_id: str | None = None,
    trace_name: str | None = None,
    user_id: str | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict:
    """把 Langfuse 追踪注入 LangChain config（agent / chain 调用用）。

    适用：agent.stream/invoke、BaseAgent.run 等「chain 路径」——会触发 on_chain_start，
    CallbackHandler 从 config.metadata 的 langfuse_* 前缀自动解析 trace 属性。
    未启用时原样返回 config（无副作用）。

    Args:
        config: 原始 LangChain config（可为 None，会返回新 dict）
        session_id: 会话 ID（Langfuse session 视图按此分组多轮对话）
        trace_id: 应用侧 trace_id，存入 metadata.brain_trace_id 供与本地 metrics 互查
        trace_name: trace 名称（动词式，如 "ask"、"classify-note"）
        user_id: 用户标识（可选）
        tags: 业务维度标签（如 ["rag"]）
        metadata: 附加上下文

    Returns:
        新的 config dict（不修改原对象）
    """
    if not is_enabled():
        return config

    try:
        from langfuse.langchain import CallbackHandler
    except ImportError:
        logger.debug("langfuse 未安装，跳过追踪")
        return config

    from brain.config import get_config

    cfg = get_config()

    handler = CallbackHandler()

    new_config = dict(config or {})
    callbacks = list(new_config.get("callbacks") or [])
    callbacks.append(handler)
    new_config["callbacks"] = callbacks

    # v4 trace 级属性：langfuse_* 前缀由 CallbackHandler._parse_langfuse_trace_attributes
    # 在 on_chain_start 时从 metadata 自动提取（session_id/user_id/trace_name/tags）。
    # 参考：https://langfuse.com/docs/integrations/langchain/tracing （Option 1）
    lf_meta: dict[str, Any] = {}
    if session_id:
        lf_meta["langfuse_session_id"] = session_id
    if user_id:
        lf_meta["langfuse_user_id"] = user_id
    if trace_name:
        lf_meta["langfuse_trace_name"] = trace_name
    if tags:
        lf_meta["langfuse_tags"] = tags

    # 业务 metadata：environment 隔离看板，app 标识来源，brain_trace_id 关联本地 trace
    biz_meta = dict(metadata or {})
    biz_meta["environment"] = cfg.langfuse.environment
    biz_meta["app"] = "brain"
    if trace_id:
        biz_meta["brain_trace_id"] = trace_id
    lf_meta["langfuse_metadata"] = biz_meta

    merged_meta = dict(new_config.get("metadata") or {})
    merged_meta.update(lf_meta)
    new_config["metadata"] = merged_meta

    return new_config


class _NoopTrace:
    """未启用 Langfuse 时的空 trace，所有方法无操作。"""

    def langchain_config(self, config: dict | None = None) -> dict | None:
        return config

    def update_output(self, output: Any) -> None:
        pass

    def update_metadata(self, metadata: dict[str, Any]) -> None:
        pass

    def end(self) -> None:
        pass


class _LangfuseTrace:
    """活跃的 Langfuse trace，持有 root observation。

    由 start_trace() 创建。能力：
      - langchain_config(config) 注入 CallbackHandler，LLM/tool observation 嵌套在 root 下
      - update_output(output) 设 trace 级输出（最终答案，evaluator 读这个）
      - update_metadata({...}) 追加 metadata（检索上下文，evaluator 读这个）
      - end() 结束 trace（退出 propagate 上下文 + 结束 root span）
    """

    def __init__(self, root, name: str):
        self._root = root
        self._name = name
        self._active = False
        self._prop_cm = None
        self._root_cm = None

    def langchain_config(self, config: dict | None = None) -> dict:
        from langfuse.langchain import CallbackHandler

        handler = CallbackHandler()
        new_config = dict(config or {})
        cbs = list(new_config.get("callbacks") or [])
        cbs.append(handler)
        new_config["callbacks"] = cbs
        return new_config

    def update_output(self, output: Any) -> None:
        """设 trace 级输出（最终答案）。evaluator 从 observation.output 读取。"""
        if self._root is not None:
            try:
                self._root.update(output=output)
            except Exception as e:
                logger.debug(f"Langfuse update_output 失败（忽略）: {e}")

    def update_metadata(self, metadata: dict[str, Any]) -> None:
        """追加 metadata（检索上下文等）。evaluator 从 observation.metadata 读取。"""
        if self._root is not None:
            try:
                self._root.update(metadata=metadata)
            except Exception as e:
                logger.debug(f"Langfuse update_metadata 失败（忽略）: {e}")

    def end(self) -> None:
        """结束 trace：退出 propagate 上下文，结束 root span。

        流式生成器在 finally 中调用，确保 trace 属性和 span 正确收尾。
        重复调用安全（_active 标记）。
        """
        if not self._active:
            return
        self._active = False
        try:
            if self._prop_cm is not None:
                self._prop_cm.__exit__(None, None, None)
            # 退出 root span 的 context manager（结束 span，trace 立即可见）
            root_cm = getattr(self, "_root_cm", None)
            if root_cm is not None:
                root_cm.__exit__(None, None, None)
        except Exception as e:
            logger.debug(f"Langfuse trace end 失败（忽略）: {e}")


def start_trace(
    name: str,
    *,
    session_id: str | None = None,
    trace_id: str | None = None,
    user_id: str | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    input: Any = None,
) -> _LangfuseTrace | _NoopTrace:
    """开始一个 Langfuse trace，返回可手动管理生命周期的 trace 对象。

    适用于流式生成器（ask 路由的 event_stream）——trace 跨越多个 yield，
    无法用单个 with 块覆盖，需在生成器开始时 start、结束/异常时 end。

    关键能力（faithfulness 评测依赖）：root observation 汇总 input/output/metadata，
    observation-level evaluator（如 LLM-as-a-Judge faithfulness）只看单个 observation
    的数据，所以 question/answer/context 三者都汇总到 root。

    用法::

        lf = start_trace("ask", session_id=sid, trace_id=tid, tags=["rag"],
                         input={"question": q})
        try:
            cfg = lf.langchain_config(base_config)
            for chunk in agent.stream(..., config=cfg):
                yield ...
            lf.update_output(final_answer)
            lf.update_metadata({"context": retrieved_context})
        finally:
            lf.end()
    """
    if not is_enabled():
        return _NoopTrace()

    try:
        from langfuse import get_client, propagate_attributes
    except ImportError:
        logger.debug("langfuse 未安装，跳过追踪")
        return _NoopTrace()

    from brain.config import get_config

    cfg = get_config()

    try:
        lf = get_client()
        biz_meta = dict(metadata or {})
        biz_meta["environment"] = cfg.langfuse.environment
        biz_meta["app"] = "brain"
        if trace_id:
            biz_meta["brain_trace_id"] = trace_id

        # start_as_current_observation 建 trace root（定 name/input/output/metadata），
        # propagate_attributes 设 trace 级归属维度（session/user/tags）。
        # 返回的是 context manager，需 __enter__() 拿到真正的 LangfuseSpan；
        # span 可 update（output/metadata），供 LLM-as-a-Judge evaluator 读取
        # （observation-level evaluator 只看单个 observation 的 input/output/metadata，
        # 所以 question/answer/context 三者都汇总到 root）。
        root_cm = lf.start_as_current_observation(name=name, as_type="span")
        root = root_cm.__enter__()
        if input is not None:
            root.update(input=input)
        prop_kwargs: dict[str, Any] = {"metadata": biz_meta}
        if session_id:
            prop_kwargs["session_id"] = session_id
        if user_id:
            prop_kwargs["user_id"] = user_id
        if tags:
            prop_kwargs["tags"] = tags
        prop_cm = propagate_attributes(**prop_kwargs)
        prop_cm.__enter__()  # 进入 propagate 上下文（trace 属性生效）

        trace = _LangfuseTrace(root=root, name=name)
        trace._root_cm = root_cm  # type: ignore[attr-defined]
        trace._prop_cm = prop_cm  # type: ignore[attr-defined]
        trace._active = True
        return trace
    except Exception as e:
        logger.debug(f"Langfuse trace 创建失败，降级为 Noop: {e}")
        return _NoopTrace()


@contextmanager
def langfuse_trace(
    name: str,
    *,
    session_id: str | None = None,
    trace_id: str | None = None,
    user_id: str | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    input: Any = None,
) -> Iterator[_LangfuseTrace | _NoopTrace]:
    """创建一个 Langfuse trace 上下文（with 块用法，直接 LLM 调用用）。

    适用于同步、调用可在 with 块内完成的场景（digest/query_rewriter/judge）。
    流式生成器场景（ask 路由 event_stream，trace 跨多个 yield）用 start_trace()。

    用法::

        with langfuse_trace("daily-digest", tags=["digest"]) as lf:
            cfg = lf.langchain_config()
            llm.invoke(messages, config=cfg)
    """
    trace = start_trace(
        name, session_id=session_id, trace_id=trace_id, user_id=user_id,
        tags=tags, metadata=metadata, input=input,
    )
    try:
        yield trace
    finally:
        trace.end()


def flush() -> None:
    """同步刷新 Langfuse 事件队列。

    短生命周期进程（CLI 命令、脚本）退出前调用，确保 trace 已发送到服务端。
    长驻服务（FastAPI）无需调用——后台批量发送。
    """
    if not is_enabled():
        return
    try:
        from langfuse import get_client

        get_client().flush()
    except Exception as e:
        logger.debug(f"Langfuse flush 失败（忽略）: {e}")


def shutdown() -> None:
    """关闭 Langfuse 客户端，刷新所有待发送事件。

    进程退出时调用（CLI 入口、lifespan shutdown）。
    """
    if not is_enabled():
        return
    try:
        from langfuse import get_client

        get_client().shutdown()
    except Exception as e:
        logger.debug(f"Langfuse shutdown 失败（忽略）: {e}")
