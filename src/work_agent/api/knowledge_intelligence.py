from fastapi import APIRouter, Depends, HTTPException, Query

from work_agent.api.deps import get_current_user, require_permission
from work_agent.api.schemas import GraphOut, SimilarDocOut
from work_agent.core.container import (
    knowledge_graph_service,
    knowledge_quality_service,
    similar_document_service,
)
from work_agent.db.models import User


router = APIRouter(
    prefix="/api/admin/knowledge",
    tags=["knowledge-intelligence"]
)


@router.get(
    "/quality",
    response_model=dict
)
def knowledge_quality(
        current_user: User = Depends(require_permission("document:view"))
):

    """
    知识库质量体检（按租户隔离）

    覆盖/一致性/分类/重复/健康度
    """

    return knowledge_quality_service.analyze(
        tenant_id=current_user.tenant_id
    )


@router.get(
    "/similar/{document_id}",
    response_model=list[SimilarDocOut]
)
def similar_documents(
        document_id: int,
        threshold: float = Query(0.8, ge=0.0, le=1.0),
        current_user: User = Depends(require_permission("document:view"))
):

    """
    检测某文档的相似文档（同租户，排除自身）

    用于发现知识库重复/高度相似的文档
    """

    try:

        results = similar_document_service.find_similar(
            document_id=document_id,
            tenant_id=current_user.tenant_id,
            threshold=threshold,
        )

    except ValueError as exc:

        raise HTTPException(
            status_code=404,
            detail=str(exc),
        )

    return results


@router.get(
    "/graph",
    response_model=GraphOut
)
def knowledge_graph(
        current_user: User = Depends(require_permission("document:view"))
):

    """
    知识图谱（节点 + 边，按租户隔离）

    节点按概念名跨文档合并，degree=关系度数
    """

    return knowledge_graph_service.get_graph(
        tenant_id=current_user.tenant_id
    )


@router.post(
    "/graph/build"
)
def build_knowledge_graph(
        document_id: int | None = Query(None),
        current_user: User = Depends(require_permission("document:create"))
):

    """
    按需构建知识图谱

    document_id 缺省时重建当前租户全部 ready 文档
    """

    if document_id is not None:

        try:

            return knowledge_graph_service.build_for_document(
                document_id,
                current_user.tenant_id,
            )

        except ValueError as exc:

            raise HTTPException(
                status_code=404,
                detail=str(exc),
            )

    return knowledge_graph_service.build_all(
        tenant_id=current_user.tenant_id
    )
