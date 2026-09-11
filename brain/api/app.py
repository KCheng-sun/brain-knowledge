"""Brain FastAPI 应用——组装实例 + 中间件 + 路由 + 静态文件。

启动: brain ui  或  uvicorn brain.api.server:app
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from brain.api.deps import _init


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化服务，关闭时可放清理逻辑。"""
    _init()
    yield
    # shutdown：调度器停止等清理可放这里（当前由进程退出回收）
    # Phase 5G：关闭 Langfuse 客户端，刷新待发送 trace
    try:
        from brain.langfuse_tracing import shutdown

        shutdown()
    except Exception:
        pass


app = FastAPI(title="Brain API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# 路由装配——按业务域
# ============================================================

from brain.api.routes.ask import router as ask_router  # noqa: E402
from brain.api.routes.eval import router as eval_router  # noqa: E402
from brain.api.routes.notes import router as notes_router  # noqa: E402
from brain.api.routes.observability import router as observability_router  # noqa: E402
from brain.api.routes.prompts import router as prompts_router  # noqa: E402
from brain.api.routes.review import router as review_router  # noqa: E402
from brain.api.routes.scheduler import router as scheduler_router  # noqa: E402
from brain.api.routes.search import router as search_router  # noqa: E402
from brain.api.routes.sources import router as sources_router  # noqa: E402

app.include_router(notes_router)
app.include_router(search_router)
app.include_router(ask_router)
app.include_router(sources_router)
app.include_router(scheduler_router)
app.include_router(observability_router)
app.include_router(eval_router)
app.include_router(prompts_router)
app.include_router(review_router)

# ============================================================
# 前端静态文件
# ============================================================

_frontend_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"

# 挂载静态资源目录（JS/CSS 等），否则 /assets/*.js 返回 404
_assets_dir = _frontend_dist / "assets"
if _assets_dir.exists():
    app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="assets")


@app.get("/")
def serve_frontend():
    index_path = _frontend_dist / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return {"message": "前端未构建。运行: cd frontend && npm run build"}


@app.get("/{full_path:path}")
def serve_spa(full_path: str):
    """SPA fallback：所有非 /api 路径返回 index.html（支持前端路由刷新）。"""
    # /assets/* 已由 StaticFiles 处理，不会走到这里
    index_path = _frontend_dist / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return {"message": "前端未构建"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("brain.api.server:app", host="127.0.0.1", port=7860, reload=True)
