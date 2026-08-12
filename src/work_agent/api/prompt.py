from fastapi import APIRouter, Depends, HTTPException

from work_agent.api.deps import get_current_user, require_permission
from work_agent.api.schemas import (
    PromptActivateRequest,
    PromptCreateDraftRequest,
    PromptHistoryOut,
    PromptListOut,
)
from work_agent.core.container import prompt_governance_service
from work_agent.db.models import User


router = APIRouter(
    prefix="/api/admin/prompts",
    tags=["prompt"]
)


@router.get(
    "",
    response_model=list[PromptListOut]
)
def list_prompts(
        current_user: User = Depends(require_permission("system:manage"))
):

    """
    Prompt 治理清单（含 active 版本）
    """

    return prompt_governance_service.list_prompts()


@router.get(
    "/{name}/history",
    response_model=list[PromptHistoryOut]
)
def prompt_history(
        name: str,
        current_user: User = Depends(require_permission("system:manage"))
):

    """
    某 Prompt 的版本历史
    """

    return prompt_governance_service.list_history(name)


@router.post(
    "/{name}/versions"
)
def create_draft(
        name: str,
        payload: PromptCreateDraftRequest,
        current_user: User = Depends(require_permission("system:manage"))
):

    """
    创建 Prompt 草稿（版本自动递增）
    """

    if not payload.content.strip():

        raise HTTPException(
            status_code=400,
            detail="Prompt 内容不能为空"
        )

    return prompt_governance_service.create_draft(
        name=name,
        content=payload.content,
        description=payload.description,
        updated_by=current_user.username,
    )


@router.post(
    "/{name}/activate"
)
def activate_version(
        name: str,
        payload: PromptActivateRequest,
        current_user: User = Depends(require_permission("system:manage"))
):

    """
    激活指定版本（唯一 active，其余 deprecated；清缓存立即生效）
    """

    result = prompt_governance_service.activate(
        name=name,
        version=payload.version,
        updated_by=current_user.username,
        audit_tenant_id=current_user.tenant_id,
        audit_user_id=current_user.id,
    )

    if not result:

        raise HTTPException(
            status_code=404,
            detail="版本不存在或当前状态不可激活",
        )

    return result


@router.post(
    "/seed"
)
def seed_prompts(
        current_user: User = Depends(require_permission("system:manage"))
):

    """
    将 prompts/*.txt 作为 v1.0 基线入库（幂等）
    """

    seeded = prompt_governance_service.seed_from_files()

    return {
        "seeded": seeded,
    }
