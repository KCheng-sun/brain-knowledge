"""提示词统一读取入口（Phase 5E FR56 + Phase 5G FR66 接入 Langfuse）。

读取优先级（高 → 低）：
  1. Langfuse Prompt Management（label="production"，主源）
  2. 本地 prompts 表（MetadataStore，回退 1）
  3. prompt_defaults.py（DEFAULT_PROMPTS，回退 2）

Langfuse 接入要点（踩坑总结见 CLAUDE.md 5G）：
  - Langfuse 用 {{var}} 双花括号，迁移时已从 str.format 的 {var} 转换
  - prompt.compile(**kwargs) 渲染变量，纯文本提示词无变量则原样返回
  - get_prompt 自带 fallback 参数（Langfuse 不可达时用），但为了保留「数据库可编辑」
    的本地能力，我们手动做三级回退而非依赖 SDK fallback
  - Langfuse 客户端侧缓存（cache_ttl_seconds），首次 fetch 后零延迟，Langfuse 宕机
    仍用缓存——符合「可观测性/管理不能影响主流程」原则
  - 无凭证/禁用时跳过 Langfuse，直接走数据库+默认值（与 5G 追踪降级一致）

用法::

    from brain.prompts import get_prompt, get_prompt_template

    # 纯文本提示词（Agent system_prompt）
    system_prompt = get_prompt("researcher")

    # 含占位符的模板提示词（变量在调用处传入）
    rendered = get_prompt_template("judge", question=q, answer=a, context=c)
"""

from __future__ import annotations

from loguru import logger

# 进程内缓存：prompt_key → content（仅缓存数据库/默认值回退结果，
# Langfuse 有自己的客户端缓存，不在此缓存）
_cache: dict[str, str] = {}

# Langfuse prompt name 与应用 prompt_key 的映射：
# 应用用 snake_case（query_rewriter），Langfuse 用 hyphen（query-rewriter）
# 统一在此转换，调用方无感


def _langfuse_name(prompt_key: str) -> str:
    """prompt_key → Langfuse prompt name（snake_case → hyphen-case）。"""
    return prompt_key.replace("_", "-")


def _langfuse_enabled() -> bool:
    """Langfuse 提示词管理是否启用（复用 tracing 的启用判定）。

    启用条件：tracing 开关为 True 且有 PUBLIC_KEY。
    提示词管理与追踪共享同一套凭证和开关——无凭证时两者都不可用。
    """
    from brain.langfuse_tracing import is_enabled

    return is_enabled()


def _get_from_langfuse(prompt_key: str) -> str | None:
    """从 Langfuse 读取提示词（label=production）。

    返回 prompt.prompt（原始模板文本，含 {{var}} 占位符未渲染）。
    失败/不存在返回 None（调用方回退到数据库）。
    """
    if not _langfuse_enabled():
        return None
    try:
        from langfuse import get_client

        lf = get_client()
        lf_prompt = lf.get_prompt(_langfuse_name(prompt_key), label="production")
        return lf_prompt.prompt
    except Exception as e:
        # Langfuse 不可达/prompt 不存在——降级到数据库，不崩
        logger.debug(f"Langfuse 读取提示词 {prompt_key} 失败，回退数据库: {e}")
        return None


def _get_store():
    """获取已初始化的 MetadataStore 单例（不触发初始化，避免循环导入和测试污染）。

    只读取 deps 模块级变量当前值——若 API 层尚未 _init() 则返回 None，
    调用方回退到 prompt_defaults 默认值。这样 prompts 层不会反向触发服务初始化
    （原实现读 server._metadata_store 也是 None，行为一致）。
    """
    from brain.api import deps

    return deps._metadata_store


def _get_from_db_or_default(prompt_key: str) -> str:
    """从本地 prompts 表或默认值读取（回退路径，带进程内缓存）。"""
    if prompt_key in _cache:
        return _cache[prompt_key]

    store = _get_store()
    row = store.get_prompt(prompt_key) if store else None

    if row and row["enabled"]:
        _cache[prompt_key] = row["content"]
        return row["content"]

    # 回退到默认值（开发期/表未初始化时）
    if row and not row["enabled"]:
        logger.warning(f"提示词 {prompt_key} 已禁用，回退到默认值")
    else:
        logger.warning(f"提示词 {prompt_key} 不存在于数据库，回退到默认值")

    from brain.storage.prompt_defaults import DEFAULT_PROMPTS

    for key, _name, _desc, content, _tmpl in DEFAULT_PROMPTS:
        if key == prompt_key:
            _cache[prompt_key] = content
            return content

    # 真的不存在——返回空串避免崩溃
    logger.error(f"提示词 {prompt_key} 无默认值，返回空串")
    return ""


def get_prompt(prompt_key: str) -> str:
    """读取提示词正文（纯文本，不含占位符渲染）。

    优先级：Langfuse（production）→ 本地 prompts 表 → prompt_defaults。
    模板提示词返回的是**原始模板**（含 {{var}} 占位符），需用 get_prompt_template 渲染。
    纯文本提示词直接返回正文。

    Langfuse 不可达时自动回退到本地数据库（带缓存），主流程不受影响。
    """
    # 1. 优先 Langfuse（不缓存——Langfuse SDK 自带客户端缓存）
    lf_content = _get_from_langfuse(prompt_key)
    if lf_content is not None:
        return lf_content

    # 2. 回退数据库 + 默认值（带进程内缓存）
    return _get_from_db_or_default(prompt_key)


def get_prompt_template(prompt_key: str, **kwargs) -> str:
    """读取并渲染模板提示词。

    Langfuse 源：用 prompt.compile(**kwargs) 渲染 {{var}} 占位符。
    本地回退源：用 str.format(**kwargs) 渲染 {var} 占位符（5E 原有逻辑）。

    Args:
        prompt_key: 提示词 key（如 "judge"）
        **kwargs: 模板变量

    Returns:
        渲染后的完整字符串
    """
    # 1. 优先 Langfuse：compile 渲染
    if _langfuse_enabled():
        try:
            from langfuse import get_client

            lf = get_client()
            lf_prompt = lf.get_prompt(_langfuse_name(prompt_key), label="production")
            return lf_prompt.compile(**kwargs)
        except Exception as e:
            logger.debug(f"Langfuse 渲染提示词 {prompt_key} 失败，回退本地: {e}")

    # 2. 回退本地数据库/默认值：str.format 渲染（5E 原有逻辑）
    content = _get_from_db_or_default(prompt_key)
    try:
        return content.format(**kwargs)
    except KeyError as e:
        logger.error(f"提示词 {prompt_key} 渲染失败：缺少参数 {e}")
        return content


def reload_prompts() -> None:
    """清空提示词缓存（编辑保存后调用，下次读取重新查库）。

    注意：此函数只清本地数据库回退的缓存。Langfuse 源的缓存由 SDK 管理
    （cache_ttl_seconds，默认 5s 自动刷新），编辑 Langfuse 后无需手动清。
    供 API 的 PUT /api/prompts/{key} 在更新本地库后调用。
    """
    _cache.clear()
    logger.info("提示词缓存已清空，下次读取将重新查库")


def reload_prompt(prompt_key: str) -> None:
    """清空单个提示词的缓存。"""
    _cache.pop(prompt_key, None)
