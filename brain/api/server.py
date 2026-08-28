"""兼容垫片——re-export app 并动态代理 deps 单例。

历史代码的访问点：
  - `uvicorn brain.api.server:app`
  - `import brain.api.server as server_module` + `server_module._metadata_store`（测试 fixture）
  - `from brain.api.server import _metadata_store`（brain.prompts，已改为 deps）
  - `server_module._init()`（测试 fixture 重置）

拆分后这些保持不变。新代码应直接 from brain.api.app import app / from brain.api.deps import get_*。
单例变量通过模块级 __getattr__/__setattr__ 动态代理到 deps，保证测试 fixture
重置 server_module._xxx 时真正改的是 deps 里的源变量（路由用 deps 访问器读取）。
"""

from brain.api import deps as _deps
from brain.api.app import app  # noqa: F401

# 需要代理到 deps 的单例变量名
_PROXY_NAMES = {
    "_pipeline", "_vector_store", "_metadata_store", "_hybrid_searcher",
    "_checkpointer", "_scheduler", "_watcher",
}


def _init():
    """兼容垫片：转发到 deps._init。"""
    _deps._init()


def __getattr__(name: str):
    # 读单例变量时动态代理到 deps 的当前值
    if name in _PROXY_NAMES:
        return getattr(_deps, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __setattr__(name: str, value):
    # 测试 fixture 重置单例时写入 deps 源变量
    if name in _PROXY_NAMES:
        setattr(_deps, name, value)
    else:
        # 其他属性走正常模块赋值（如 import 绑定、显式赋值）
        globals()[name] = value
