from fastapi import APIRouter, Depends, HTTPException

from sqlalchemy.orm import Session

from work_agent.api.deps import get_db, get_current_user, require_permission
from work_agent.api.schemas import ConfigOut, ConfigUpdateRequest
from work_agent.core.config_defs import CONFIG_DEFINITIONS
from work_agent.core.container import agent_config_service
from work_agent.db.models import User
from work_agent.services.rbac_service import RBACService


router = APIRouter(
    prefix="/api/admin/configs",
    tags=["config"]
)


@router.get(
    "",
    response_model=list[ConfigOut]
)
def list_configs(
        current_user: User = Depends(require_permission("system:manage"))
):

    """
    当前租户生效配置清单（内置默认 + 平台 + 租户覆盖）
    """

    return agent_config_service.list_configs(
        tenant_id=current_user.tenant_id
    )


@router.get(
    "/{config_key}",
    response_model=ConfigOut
)
def get_config(
        config_key: str,
        current_user: User = Depends(require_permission("system:manage"))
):

    """
    某配置项生效值
    """

    _validate_key(config_key)

    value = agent_config_service.get(
        config_key,
        current_user.tenant_id,
    )

    return {
        "key": config_key,
        "value": value,
        "scope": _effective_scope(
            config_key,
            current_user.tenant_id,
        ),
        "description": CONFIG_DEFINITIONS[config_key]["description"],
        "updated_by": "",
        "updated_at": None,
    }


@router.put(
    "/{config_key}",
    response_model=ConfigOut
)
def update_config(
        config_key: str,
        payload: ConfigUpdateRequest,
        db: Session = Depends(get_db),
        current_user: User = Depends(require_permission("system:manage"))
):

    """
    设置配置项

    scope=platform 仅限 SUPER_ADMIN（平台级全局生效）
    scope=tenant 为该租户覆盖
    """

    _validate_key(config_key)

    if payload.scope not in ("tenant", "platform"):

        raise HTTPException(
            status_code=400,
            detail="scope 仅支持 tenant / platform"
        )

    tenant_id = current_user.tenant_id

    if payload.scope == "platform":

        roles = RBACService().get_role_codes(
            db,
            current_user.id,
        )

        if "SUPER_ADMIN" not in roles:

            raise HTTPException(
                status_code=403,
                detail="仅超级管理员可修改平台级配置"
            )

        tenant_id = ""

    agent_config_service.set(
        key=config_key,
        value=payload.value,
        tenant_id=tenant_id,
        updated_by=current_user.username,
        description=payload.description,
    )

    value = agent_config_service.get(
        config_key,
        current_user.tenant_id,
    )

    return {
        "key": config_key,
        "value": value,
        "scope": (
            "platform"
            if tenant_id == ""
            else "tenant"
        ),
        "description": payload.description
        or CONFIG_DEFINITIONS[config_key]["description"],
        "updated_by": current_user.username,
        "updated_at": None,
    }


def _validate_key(key: str) -> None:

    if key not in CONFIG_DEFINITIONS:

        raise HTTPException(
            status_code=400,
            detail=f"未知配置项: {key}",
        )


def _effective_scope(
        key: str,
        tenant_id: str
) -> str:

    """
    判定配置项当前生效层级
    """

    from work_agent.services.config_service import agent_config_service

    db_scope = agent_config_service._effective_scope(
        key,
        tenant_id,
    )

    return db_scope
