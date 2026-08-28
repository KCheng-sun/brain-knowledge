"""配置系统。

配置优先级（从低到高）：
  1. 代码默认值
  2. .env 文件
  3. 环境变量（BRAIN_ 前缀）
  4. config.yaml（Phase 2 引入）

用法:
    from brain.config import get_config
    cfg = get_config()
    print(cfg.storage.data_dir)
"""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# ============================================================
# 配置子模型
# ============================================================


# 项目根目录（brain/config.py 的上两级）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


class StorageSettings(BaseSettings):
    """存储路径配置——默认存在项目目录下的 data/ 中。"""

    model_config = SettingsConfigDict(env_prefix="BRAIN_STORAGE_")

    data_dir: Path = _PROJECT_ROOT / "data"
    notes_dir: Path = _PROJECT_ROOT / "data" / "notes"
    chroma_dir: Path = _PROJECT_ROOT / "data" / "chroma"
    db_path: Path = _PROJECT_ROOT / "data" / "metadata.db"


class DatabaseSettings(BaseSettings):
    """关系型数据库配置（Phase 5D：支持 MySQL）。"""

    model_config = SettingsConfigDict(env_prefix="BRAIN_DB_")

    # None=用 SQLite（db_path），指定则用 MySQL
    host: str | None = None
    port: int = 3306
    user: str = "root"
    password: str = ""
    database: str = "brain"
    charset: str = "utf8mb4"


class LLMSettings(BaseSettings):
    """LLM 配置"""

    model_config = SettingsConfigDict(env_prefix="BRAIN_LLM_")

    provider: str = "deepseek"
    model: str = "deepseek-chat"
    api_key: str = Field(default="", alias="DEEPSEEK_API_KEY")
    max_tokens: int = 4096
    temperature: float = 0.3
    # Phase 5C FR51：LLM 调用容灾（透传给 SDK 原生重试，自动处理 429/5xx/超时）
    max_retries: int = 3              # SDK 重试次数（含首次）


class EmbeddingSettings(BaseSettings):
    """Embedding 配置"""

    model_config = SettingsConfigDict(env_prefix="BRAIN_EMBEDDING_")

    provider: str = "siliconflow"
    model_name: str = "BAAI/bge-large-zh-v1.5"
    base_url: str = "https://api.siliconflow.cn/v1"
    api_key: str = Field(default="", alias="SILICONFLOW_API_KEY")
    device: str = "cpu"  # 仅 local provider 使用


class IngestionSettings(BaseSettings):
    """摄入配置"""

    model_config = SettingsConfigDict(env_prefix="BRAIN_INGESTION_")

    chunk_size: int = 400  # 分块大小（字符数）——BGE 模型 512 token 上限内
    chunk_overlap: int = 80  # 分块重叠长度
    debounce_seconds: int = 2  # 文件监听防抖时间


class AgentSettings(BaseSettings):
    """Agent 配置（Phase 2 启用）"""

    model_config = SettingsConfigDict(env_prefix="BRAIN_AGENTS_")

    classifier_enabled: bool = True
    connector_enabled: bool = True
    synthesizer_enabled: bool = False
    min_confidence: float = 0.6
    top_k_candidates: int = 20
    min_strength: float = 0.5


class CostSettings(BaseSettings):
    """成本治理配置（Phase 5B FR48）"""

    model_config = SettingsConfigDict(env_prefix="BRAIN_COST_")

    daily_token_limit: int = 500_000      # 日 token 配额
    monthly_token_limit: int = 5_000_000  # 月 token 配额
    daily_cost_limit: float = 10.0        # 日成本上限（¥）
    recursion_limit: int = 25             # Agent 最大递归步数（防死循环）


class RetrievalSettings(BaseSettings):
    """RAG 检索配置（Phase 5F FR58-60）。

    混合检索 = BM25 + 向量 + RRF 融合；可选 Rerank 精排和查询改写。
    任一环节失败均降级，不阻塞主流程。
    """

    model_config = SettingsConfigDict(env_prefix="BRAIN_RETRIEVAL_")

    hybrid_enabled: bool = True          # 混合检索总开关（False=纯向量）
    rrf_k: int = 60                      # RRF 融合常数（标准值 60）
    candidate_top_n: int = 30            # RRF 融合后送 Rerank 的候选数
    rerank_enabled: bool = True          # Rerank 精排开关
    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    rerank_top_n: int = 30               # Rerank 输入候选数（= candidate_top_n）
    query_rewrite_enabled: bool = True   # 查询改写开关
    query_rewrite_count: int = 3         # Multi-Query 改写版本数


# ============================================================
# 顶层配置
# ============================================================


class AppConfig(BaseSettings):
    """应用顶层配置，聚合所有子配置。"""

    model_config = SettingsConfigDict(
        env_prefix="BRAIN_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    storage: StorageSettings = Field(default_factory=StorageSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    embedding: EmbeddingSettings = Field(default_factory=EmbeddingSettings)
    ingestion: IngestionSettings = Field(default_factory=IngestionSettings)
    agents: AgentSettings = Field(default_factory=AgentSettings)
    cost: CostSettings = Field(default_factory=CostSettings)
    retrieval: RetrievalSettings = Field(default_factory=RetrievalSettings)

    # 应用级配置
    dry_run: bool = False  # mock LLM 调用
    log_level: str = "INFO"  # DEBUG | INFO | WARNING | ERROR


# ============================================================
# 单例
# ============================================================

_config: AppConfig | None = None


def get_config() -> AppConfig:
    """获取全局配置单例。首次调用时从环境变量/.env 加载。"""
    global _config
    if _config is None:
        # 确保 .env 被加载
        from dotenv import load_dotenv

        # 从项目根目录加载 .env（不依赖当前工作目录）
        env_path = _PROJECT_ROOT / ".env"
        load_dotenv(dotenv_path=env_path, override=True)
        _config = AppConfig()
        _ensure_directories(_config)
        _setup_file_logging(_config)
    return _config


def _ensure_directories(cfg: AppConfig) -> None:
    """确保数据目录存在。"""
    cfg.storage.data_dir.mkdir(parents=True, exist_ok=True)
    cfg.storage.notes_dir.mkdir(parents=True, exist_ok=True)
    cfg.storage.chroma_dir.mkdir(parents=True, exist_ok=True)
    cfg.storage.db_path.parent.mkdir(parents=True, exist_ok=True)


def _setup_file_logging(cfg: AppConfig) -> None:
    """配置 loguru 滚动文件日志（终端之外持久化，重启不丢）。"""
    from loguru import logger

    log_dir = cfg.storage.data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    # 每个文件最多 5MB，保留 3 个滚动文件（人类可读格式）
    logger.add(
        log_dir / "brain.log",
        rotation="5 MB",
        retention=3,
        level=cfg.log_level,
        encoding="utf-8",
        enqueue=True,  # 多线程安全
        backtrace=False,
        diagnose=False,
    )

    # 结构化 JSON 日志（Phase 5A）：便于机器解析和按 trace_id 过滤
    # 字段含 timestamp/level/trace_id/agent/tool/message
    logger.add(
        log_dir / "brain.json.log",
        rotation="5 MB",
        retention=7,
        level=cfg.log_level,
        encoding="utf-8",
        enqueue=True,
        serialize=True,  # 输出 JSON 格式
        backtrace=False,
        diagnose=False,
    )
