"""提示词统一读取入口（Phase 5E FR56）。

所有 Agent 从这里读取 system_prompt，不再硬编码。
数据存在 prompts 表（MetadataStore 管理），本模块负责：
  - 从库读取 + 进程内字典缓存（避免每次 Agent 调用都查库）
  - 模板渲染（含 {占位符} 的提示词用 str.format）
  - 缓存失效（编辑保存后调 reload_prompts 即时生效）

用法::

    from brain.prompts import get_prompt, get_prompt_template

    # 纯文本提示词
    system_prompt = get_prompt("researcher")

    # 含占位符的模板提示词
    rendered = get_prompt_template("judge", question=q, answer=a, context=c)
"""

from __future__ import annotations

from loguru import logger

# 进程内缓存：prompt_key → content
# Agent 运行时高频读取，缓存避免每次查库；编辑后 reload_prompts() 清缓存
_cache: dict[str, str] = {}


def _get_store():
    """懒加载 MetadataStore 单例（避免循环导入）。"""
    from brain.api.server import _metadata_store

    return _metadata_store


def get_prompt(prompt_key: str) -> str:
    """读取提示词正文（纯文本，不含占位符渲染）。

    首次读取查库并缓存；后续直接命中缓存。
    若提示词不存在或未启用，回退到 prompt_defaults 中的默认值并告警。
    """
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


def get_prompt_template(prompt_key: str, **kwargs) -> str:
    """读取并渲染模板提示词（含 {占位符}，用 str.format 填充）。

    供 judge 等需要动态填充内容的提示词使用。
    """
    content = get_prompt(prompt_key)
    try:
        return content.format(**kwargs)
    except KeyError as e:
        logger.error(f"提示词 {prompt_key} 渲染失败：缺少参数 {e}")
        return content


def reload_prompts() -> None:
    """清空提示词缓存（编辑保存后调用，下次读取重新查库）。

    供 API 的 PUT /api/prompts/{key} 在更新后调用，实现即时生效。
    """
    _cache.clear()
    logger.info("提示词缓存已清空，下次读取将重新查库")


def reload_prompt(prompt_key: str) -> None:
    """清空单个提示词的缓存。"""
    _cache.pop(prompt_key, None)
