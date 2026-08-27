"""pytest 共享 fixtures。

提供临时目录中的 VectorStore、MetadataStore 等测试基础设施。
所有测试使用临时目录，不触碰真实用户数据。
"""

import asyncio
import tempfile
from pathlib import Path
from typing import Callable

import pytest

from brain.ingestion.parser import DocumentParser
from brain.storage.metadata import MetadataStore
from brain.storage.vector_store import VectorStore


# ============================================================
# Embedding Mock — 返回随机向量，避免加载真实的 sentence-transformers
# ============================================================


@pytest.fixture
def embedding_fn() -> Callable:
    """Mock embedding 函数: 返回 384 维固定向量。"""

    def _mock_embed(texts: list[str]) -> list[list[float]]:
        # 用文本长度的哈希生成伪随机但确定性的向量
        import hashlib

        result = []
        for text in texts:
            h = hashlib.sha256(text.encode()).digest()
            # 扩展到 384 维
            vec = []
            for i in range(384):
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
    """临时目录，测试结束后自动清理。

    ChromaDB 在 Windows 上退出后仍短暂持有文件句柄，
    清理失败时忽略（ignore_cleanup_errors），交给系统临时目录回收。
    """
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        yield Path(tmp)


@pytest.fixture
def chroma_dir(temp_dir: Path) -> Path:
    """ChromaDB 持久化目录。"""
    path = temp_dir / "chroma"
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture
def db_path(temp_dir: Path) -> Path:
    """SQLite 数据库路径。"""
    return temp_dir / "test_metadata.db"


# ============================================================
# 存储层 fixtures
# ============================================================


@pytest.fixture
def vector_store(chroma_dir: Path, embedding_fn: Callable) -> VectorStore:
    """返回使用 mock embedding 和临时目录的 VectorStore。"""
    return VectorStore(persist_dir=chroma_dir, embedding_fn=embedding_fn)


@pytest.fixture
def metadata_store(db_path: Path, monkeypatch) -> MetadataStore:
    """返回使用临时 SQLite 数据库的 MetadataStore（已初始化）。

    强制 SQLite 模式（忽略全局 MySQL 配置），保证测试隔离。
    """
    import brain.config as config_module
    from brain.config import DatabaseSettings

    # 强制 SQLite：把 database.host 设为 None
    cfg = config_module.get_config()
    monkeypatch.setattr(cfg.database, "host", None)

    store = MetadataStore(db_path=db_path)
    store.initialize()
    yield store
    store.close()


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
