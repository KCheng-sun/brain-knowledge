"""提示词业务域 API 路由（CRUD + 版本管理）。

端点:
  GET   /api/prompts                              — 列出全部提示词
  GET   /api/prompts/{key}                        — 单条详情
  PUT   /api/prompts/{key}                        — 更新内容（version 自增）
  GET   /api/prompts/{key}/versions               — 版本列表
  GET   /api/prompts/{key}/versions/{ver}         — 历史版本正文
  POST  /api/prompts/{key}/versions/{ver}/restore — 恢复历史版本
"""

from fastapi import APIRouter, HTTPException

from brain.api.deps import get_metadata_store
from brain.api.routes.prompts.models import PromptUpdateRequest

router = APIRouter(prefix="/api/prompts", tags=["prompts"])


@router.get("")
def list_prompts():
    """列出全部提示词（不含正文，列表展示用）。"""
    return get_metadata_store().list_prompts()


@router.get("/{prompt_key}")
def get_prompt_detail(prompt_key: str):
    """获取单条提示词详情（含正文）。"""
    row = get_metadata_store().get_prompt(prompt_key)
    if not row:
        raise HTTPException(status_code=404, detail="提示词不存在")
    return row


@router.put("/{prompt_key}")
def update_prompt(prompt_key: str, req: PromptUpdateRequest):
    """更新提示词内容（version 自增），并刷新缓存即时生效。"""
    ms = get_metadata_store()
    if not ms.update_prompt(prompt_key, req.content, req.enabled):
        raise HTTPException(status_code=404, detail="提示词不存在")
    # 刷新缓存，下次 Agent 调用即用新提示词
    from brain.prompts import reload_prompt

    reload_prompt(prompt_key)
    return {"message": "已更新", "prompt_key": prompt_key}


@router.get("/{prompt_key}/versions")
def list_prompt_versions(prompt_key: str):
    """列出某提示词的历史版本（按版本号降序）。"""
    return get_metadata_store().list_prompt_versions(prompt_key)


@router.get("/{prompt_key}/versions/{version}")
def get_prompt_version(prompt_key: str, version: int):
    """获取某历史版本的正文。"""
    row = get_metadata_store().get_prompt_version(prompt_key, version)
    if not row:
        raise HTTPException(status_code=404, detail="历史版本不存在")
    return row


@router.post("/{prompt_key}/versions/{version}/restore")
def restore_prompt_version(prompt_key: str, version: int):
    """恢复某历史版本为最新（该版本内容设为当前，version 继续自增）。"""
    ms = get_metadata_store()
    if not ms.restore_prompt_version(prompt_key, version):
        raise HTTPException(status_code=404, detail="历史版本不存在")
    from brain.prompts import reload_prompt

    reload_prompt(prompt_key)
    return {"message": f"已恢复 v{version}", "prompt_key": prompt_key}
