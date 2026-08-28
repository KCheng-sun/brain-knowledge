"""pytest 共享 fixtures。

提供 PostgreSQL schema 隔离的 VectorStore、MetadataStore 等测试基础设施。
每个测试用独立 schema（测完 DROP），不触碰真实数据。
"""

import hashlib
import tempfile
import uuid as _uuid
from collections.abc import Callable
from pathlib import Path

import pytest

from brain.ingestion.parser import DocumentParser
from brain.storage.metadata import MetadataStore
from brain.storage.vector_store import VectorStore

# 测试用 Postgres 连接（连 brain 库，每个测试独立 schema）
_TEST_DSN = "host=localhost port=5432 dbname=brain user=postgres password=12345678"


# ============================================================
# Embedding Mock — 返回随机向量，避免加载真实的 sentence-transformers
# ============================================================


@pytest.fixture
def embedding_fn() -> Callable:
    """Mock embedding 函数: 返回 1024 维固定向量（与 BGE-large-zh 一致）。"""

    def _mock_embed(texts: list[str]) -> list[list[float]]:
        # 用文本长度的哈希生成伪随机但确定性的向量
        result = []
        for text in texts:
            h = hashlib.sha256(text.encode()).digest()
            # 扩展到 1024 维（pgvector 列维度要求匹配）
            vec = []
            for i in range(1024):
                byte_val = h[i % len(h)]
                vec.append((byte_val / 255.0) * 2 - 1)  # [-1, 1]
            # 归一化
            norm = sum(v * v for v in vec) ** 0.5
            vec = [v / norm for v in vec]
            result.append(vec)
        return result

    return _mock_embed


# ============================================================
# 临时目录 fixtures
# ============================================================


@pytest.fixture
def temp_dir() -> Path:
    """临时目录，测试结束后自动清理。"""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        yield Path(tmp)


@pytest.fixture
def test_schema() -> str:
    """独立 Postgres schema 名（每个测试唯一），测完由调用方删除。"""
    return f"test_{_uuid.uuid4().hex[:8]}"


# ============================================================
# 存储层 fixtures
# ============================================================


@pytest.fixture
def vector_store(test_schema: str, embedding_fn: Callable) -> VectorStore:
    """返回使用 mock embedding 和独立 schema 的 VectorStore。"""
    import psycopg

    # 创建 schema
    conn = psycopg.connect(_TEST_DSN, autocommit=True)
    conn.execute(f"CREATE SCHEMA IF NOT EXISTS {test_schema}")
    conn.close()
    # dsn 带 search_path 指向该 schema（含 public 回退，找到 vector/jsonb 等扩展类型）
    dsn = f"{_TEST_DSN} options='-c search_path={test_schema},public'"
    vs = VectorStore(dsn=dsn, embedding_fn=embedding_fn)
    yield vs
    # 先关闭 VectorStore 连接，再 DROP schema（避免连接持锁导致残留）
    vs._conn.close()
    conn = psycopg.connect(_TEST_DSN, autocommit=True)
    conn.execute(f"DROP SCHEMA IF EXISTS {test_schema} CASCADE")
    conn.close()


@pytest.fixture
def metadata_store(test_schema: str) -> MetadataStore:
    """返回使用独立 schema 的 MetadataStore（已初始化）。

    每个 schema 独立建表，测试互不干扰，测完 DROP。
    """
    import psycopg

    # 创建 schema
    conn = psycopg.connect(_TEST_DSN, autocommit=True)
    conn.execute(f"CREATE SCHEMA IF NOT EXISTS {test_schema}")
    conn.close()
    dsn = f"{_TEST_DSN} options='-c search_path={test_schema},public'"
    store = MetadataStore(dsn=dsn)
    store.initialize()
    yield store
    store.close()
    # 清理 schema
    conn = psycopg.connect(_TEST_DSN, autocommit=True)
    conn.execute(f"DROP SCHEMA IF EXISTS {test_schema} CASCADE")
    conn.close()


# ============================================================
# 工具类 fixtures
# ============================================================


@pytest.fixture
def parser() -> DocumentParser:
    """返回 DocumentParser 实例。"""
    return DocumentParser()


@pytest.fixture
def sample_markdown() -> str:
    """示例 Markdown 文本。"""
    return """---
title: Python 异步编程笔记
date: 2024-08-10
tags: [python, async, programming]
---

# Python 异步编程笔记

## 1. 基本概念

Python 的异步编程基于 `asyncio` 事件循环。
`async/await` 语法让异步代码看起来像同步代码。

核心概念:
- **协程 (Coroutine)**: 用 `async def` 定义的函数
- **任务 (Task)**: 事件循环中调度的协程
- **Future**: 一个将在未来完成的结果占位符

## 2. 常见模式

### 2.1 并发执行

```python
import asyncio

async def fetch(url):
    # 模拟网络请求
    await asyncio.sleep(1)
    return f"Result from {url}"

async def main():
    urls = ["a.com", "b.com", "c.com"]
    tasks = [fetch(url) for url in urls]
    results = await asyncio.gather(*tasks)
    return results
```

### 2.2 超时控制

使用 `asyncio.wait_for()` 给协程加上超时限制。

## 3. 注意事项

1. 不要在协程中使用阻塞的 IO 操作
2. CPU 密集型任务用 `run_in_executor` 放到线程池
3. 注意协程的取消传播
"""


@pytest.fixture
def sample_markdown_file(temp_dir: Path, sample_markdown: str) -> Path:
    """写一个示例 Markdown 文件到临时目录。"""
    file_path = temp_dir / "test_note.md"
    file_path.write_text(sample_markdown, encoding="utf-8")
    return file_path
