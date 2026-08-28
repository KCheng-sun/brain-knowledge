"""Brain REST API — FastAPI 后端。

app 实例在 brain.api.app，此处 re-export 便于 `from brain.api import app`。
"""

from brain.api.app import app  # noqa: F401

__all__ = ["app"]
