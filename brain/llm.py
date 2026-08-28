"""LLM 调用统一入口。

所有 LLM 调用通过此模块获取 chat model，不直接使用原生 SDK。
切换模型只需修改配置，无需改动业务代码。

Phase 5C FR51：LLM 容灾使用 ChatOpenAI/ChatAnthropic 原生重试策略
（max_retries 透传给底层 OpenAI/Anthropic SDK，自动处理 429/5xx/超时），
不在应用层重复包装 tenacity。base.py 保留外层重试仅用于 JSON 解析失败重调。
"""

from functools import lru_cache

from langchain_core.language_models import BaseChatModel
from loguru import logger

from brain.config import get_config


@lru_cache(maxsize=1)
def get_chat_model() -> BaseChatModel:
    """获取全局 LangChain ChatModel 单例（懒加载）。

    根据 config.llm.provider 自动选择适配器：
      - deepseek → ChatOpenAI（OpenAI 兼容协议）
      - anthropic → ChatAnthropic

    用法:
        from brain.llm import get_chat_model

        llm = get_chat_model()
        response = llm.invoke("你好")
    """
    cfg = get_config()

    if cfg.dry_run:
        return _dry_run_model()

    provider = cfg.llm.provider

    if provider == "deepseek":
        return _init_deepseek(cfg)
    elif provider == "anthropic":
        return _init_anthropic(cfg)
    else:
        raise ValueError(f"不支持的 LLM provider: {provider}。可选: deepseek, anthropic")


def _init_deepseek(cfg):
    """初始化 DeepSeek（OpenAI 兼容协议）。

    max_retries 透传给底层 OpenAI SDK，自动重试 429/5xx/408/409 + 指数退避抖动。
    鉴权失败(401)/参数错误(400)不重试。
    """
    from langchain_openai import ChatOpenAI

    logger.info(f"初始化 DeepSeek: model={cfg.llm.model}, max_retries={cfg.llm.max_retries}")

    return ChatOpenAI(
        model=cfg.llm.model,
        api_key=cfg.llm.api_key,
        base_url="https://api.deepseek.com",
        max_tokens=cfg.llm.max_tokens,
        temperature=cfg.llm.temperature,
        max_retries=cfg.llm.max_retries,  # Phase 5C FR51：SDK 原生重试
    )


def _init_anthropic(cfg):
    """初始化 Anthropic Claude。

    max_retries 透传给底层 Anthropic SDK，自动重试 429/5xx + 指数退避抖动。
    """
    from langchain_anthropic import ChatAnthropic

    logger.info(f"初始化 Anthropic: model={cfg.llm.model}, max_retries={cfg.llm.max_retries}")

    return ChatAnthropic(
        model=cfg.llm.model,
        api_key=cfg.llm.api_key,
        max_tokens=cfg.llm.max_tokens,
        temperature=cfg.llm.temperature,
        max_retries=cfg.llm.max_retries,  # Phase 5C FR51：SDK 原生重试
    )


def _dry_run_model():
    """dry-run 模式下不实际调用 API。"""

    def _fake_content(*args, **kwargs):
        return "[DRY RUN] LLM 调用已跳过。"

    class _DryRunChatModel(BaseChatModel):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            from langchain_core.outputs import ChatGeneration, ChatResult

            return ChatResult(
                generations=[ChatGeneration(text=_fake_content(), message=type("_", (), {"content": _fake_content()})())]
            )

        @property
        def _llm_type(self) -> str:
            return "dry-run"

    return _DryRunChatModel()
