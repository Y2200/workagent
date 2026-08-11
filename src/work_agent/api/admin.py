from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from sqlalchemy.orm import Session

from work_agent.api.deps import get_current_user, get_db, require_permission
from work_agent.api.schemas import (
    DocumentDetail,
    DocumentOut,
    KnowledgeHitOut,
    LogPage,
    LoginRequest,
    OperationLogOut,
    OperationLogPage,
    PermissionOut,
    PermissionUpdateRequest,
    TokenResponse,
    UserOut,
)
from work_agent.core.container import (
    audit_service,
    auth_service,
    dashboard_service,
    document_service,
    knowledge_service,
    permission_service,
)
from work_agent.db.models import User


router = APIRouter(
    prefix="/api/admin",
    tags=["admin"]
)


SUPPORTED_UPLOAD_EXTENSIONS = {
    "pdf",
    "docx",
    "md",
    "txt"
}


def _client_ip(request: Request) -> str | None:

    if request.client:
        return request.client.host

    return None


def _user_agent(request: Request) -> str | None:

    return request.headers.get(
        "user-agent"
    )


@router.post(
    "/auth/login",
    response_model=TokenResponse
)
def login(
        payload: LoginRequest,
        request: Request,
        db: Session = Depends(get_db)
):

    """
    管理员登录（记录操作审计）
    """

    user = auth_service.authenticate(
        db,
        payload.username,
        payload.password
    )

    if not user:

        audit_service.log_operation(
            tenant_id="",
            action="auth.login_failed",
            target_type="user",
            ip=_client_ip(request),
            user_agent=_user_agent(request),
        )

        raise HTTPException(
            status_code=401,
            detail="用户名或密码错误"
        )

    audit_service.log_operation(
        tenant_id=user.tenant_id,
        user_id=user.id,
        action="auth.login",
        target_type="user",
        target_id=str(user.id),
        ip=_client_ip(request),
        user_agent=_user_agent(request),
    )

    token = auth_service.create_token(
        user.id
    )

    return TokenResponse(
        access_token=token
    )


@router.get(
    "/auth/me",
    response_model=UserOut
)
def me(
        current_user: User = Depends(get_current_user)
):

    """
    当前登录用户信息
    """

    return current_user


@router.post(
    "/documents/upload",
    response_model=DocumentOut,
    status_code=202
)
def upload_document(
        request: Request,
        file: UploadFile = File(...),
        category: str = Form(""),
        visibility: str = Form("public"),
        departments: str = Form(""),
        roles: str = Form(""),
        current_user: User = Depends(require_permission("document:create"))
):

    """
    上传文档

    立即返回（status=processing），管线异步处理
    客户端轮询 GET /documents/{id} 查看结果
    """

    filename = file.filename or "unnamed"

    file_type = (
        filename.rsplit(".", 1)[-1].lower()
        if "." in filename
        else ""
    )

    if file_type not in SUPPORTED_UPLOAD_EXTENSIONS:

        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {file_type}"
        )

    if visibility not in {"public", "restricted"}:

        raise HTTPException(
            status_code=400,
            detail="visibility 仅支持 public / restricted"
        )

    data = file.file.read()

    if not data:

        raise HTTPException(
            status_code=400,
            detail="文件内容为空"
        )

    document = document_service.upload(
        filename=filename,
        data=data,
        category=category,
        uploader=current_user.username,
        tenant_id=current_user.tenant_id,
        visibility=visibility,
        departments=[
            item.strip()
            for item in departments.split(",")
            if item.strip()
        ],
        roles=[
            item.strip()
            for item in roles.split(",")
            if item.strip()
        ]
    )

    # 操作审计
    audit_service.log_operation(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="document.create",
        target_type="document",
        target_id=str(document.id),
        ip=_client_ip(request),
        user_agent=_user_agent(request),
    )

    return document


@router.get(
    "/documents",
    response_model=list[DocumentOut]
)
def list_documents(
        status: str | None = Query(None),
        current_user: User = Depends(require_permission("document:view"))
):

    """
    文档列表
    """

    return document_service.list_documents(
        tenant_id=current_user.tenant_id,
        status=status
    )


@router.get(
    "/documents/{document_id}",
    response_model=DocumentDetail
)
def get_document(
        document_id: int,
        current_user: User = Depends(require_permission("document:view"))
):

    """
    文档详情（含权限与切片）
    """

    document = document_service.get_document(
        document_id,
        tenant_id=current_user.tenant_id
    )

    if not document:

        raise HTTPException(
            status_code=404,
            detail="文档不存在"
        )

    return document


@router.delete(
    "/documents/{document_id}",
    status_code=204
)
def delete_document(
        document_id: int,
        request: Request,
        current_user: User = Depends(require_permission("document:delete"))
):

    """
    删除文档（向量 + DB 记录 + MinIO 对象）
    """

    deleted = document_service.delete(
        document_id,
        tenant_id=current_user.tenant_id
    )

    if not deleted:

        raise HTTPException(
            status_code=404,
            detail="文档不存在"
        )

    # 操作审计
    audit_service.log_operation(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="document.delete",
        target_type="document",
        target_id=str(document_id),
        ip=_client_ip(request),
        user_agent=_user_agent(request),
    )


@router.get(
    "/documents/{document_id}/permissions",
    response_model=PermissionOut
)
def get_permissions(
        document_id: int,
        current_user: User = Depends(require_permission("document:permission_manage"))
):

    """
    查看文档权限
    """

    result = permission_service.get_permissions(
        document_id,
        tenant_id=current_user.tenant_id
    )

    if not result:

        raise HTTPException(
            status_code=404,
            detail="文档不存在"
        )

    return result


@router.put(
    "/documents/{document_id}/permissions",
    response_model=PermissionOut
)
def update_permissions(
        document_id: int,
        payload: PermissionUpdateRequest,
        request: Request,
        current_user: User = Depends(require_permission("document:permission_manage"))
):

    """
    修改文档权限（同步 Milvus metadata，RAG 过滤即时生效）
    """

    result = permission_service.update_permissions(
        document_id=document_id,
        tenant_id=current_user.tenant_id,
        visibility=payload.visibility,
        departments=payload.departments,
        roles=payload.roles,
        user_ids=payload.user_ids,
    )

    # 操作审计
    audit_service.log_operation(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="document.permission_update",
        target_type="document",
        target_id=str(document_id),
        ip=_client_ip(request),
        user_agent=_user_agent(request),
    )

    return result


@router.get(
    "/knowledge/search",
    response_model=list[KnowledgeHitOut]
)
def search_knowledge(
        q: str = Query(..., min_length=1),
        top_k: int = Query(5, ge=1, le=20),
        current_user: User = Depends(require_permission("document:view"))
):

    """
    知识库检索（纯召回，不调 LLM）
    """

    return knowledge_service.search(
        query=q,
        top_k=top_k,
        tenant_id=current_user.tenant_id
    )


@router.get(
    "/logs",
    response_model=LogPage
)
def list_logs(
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
        user_id: int | None = Query(None),
        channel: str | None = Query(None),
        status: str | None = Query(None),
        start_time: datetime | None = Query(None),
        end_time: datetime | None = Query(None),
        current_user: User = Depends(require_permission("audit:view"))
):

    """
    问答审计日志列表

    强制按当前管理员的租户隔离，只能看到自己租户的日志
    """

    return audit_service.list_logs(
        tenant_id=current_user.tenant_id,
        user_id=user_id,
        channel=channel,
        status=status,
        start_time=start_time,
        end_time=end_time,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/operations",
    response_model=OperationLogPage
)
def list_operations(
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
        action: str | None = Query(None),
        user_id: int | None = Query(None),
        start_time: datetime | None = Query(None),
        end_time: datetime | None = Query(None),
        current_user: User = Depends(require_permission("audit:view"))
):

    """
    操作审计列表（租户隔离）
    """

    return audit_service.list_operations(
        tenant_id=current_user.tenant_id,
        action=action,
        user_id=user_id,
        start_time=start_time,
        end_time=end_time,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/dashboard/stats",
    response_model=dict
)
def dashboard_stats(
        current_user: User = Depends(require_permission("document:view"))
):

    """
    管理驾驶舱运营统计（按租户隔离）
    """

    return dashboard_service.get_stats(
        tenant_id=current_user.tenant_id
    )


@router.get(
    "/audit/statistics",
    response_model=dict
)
def audit_statistics(
        current_user: User = Depends(require_permission("audit:view"))
):

    """
    审计统计（租户隔离）
    """

    return audit_service.get_statistics(
        tenant_id=current_user.tenant_id
    )


@router.post(
    "/audit/archive"
)
def archive_audit_logs(
        request: Request,
        current_user: User = Depends(require_permission("system:manage"))
):

    """
    归档当前租户过期日志（只标记，不删除）
    """

    result = audit_service.archive_expired(
        tenant_id=current_user.tenant_id
    )

    # 操作审计
    audit_service.log_operation(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="audit.archive",
        target_type="audit_log",
        target_id=str(result.get("archived_count", 0)),
        ip=_client_ip(request),
        user_agent=_user_agent(request),
    )

    return result
