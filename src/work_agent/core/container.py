from work_agent.rag.service import RAGService
from work_agent.storage.minio import MinioStorage
from work_agent.services.document_service import DocumentService
from work_agent.knowledge.service import KnowledgeService
from work_agent.knowledge.graph import KnowledgeGraphService
from work_agent.knowledge.similarity import SimilarDocumentService
from work_agent.knowledge.quality import KnowledgeQualityService
from work_agent.services.auth_service import AuthService
from work_agent.services.audit_service import AuditService
from work_agent.services.dashboard_service import DashboardService
from work_agent.services.permission_service import PermissionService


rag_service = RAGService()


# 文档存储与管线
# 复用 rag_service 的 embedding/store，避免重复加载 bge 模型
minio_storage = MinioStorage()

document_service = DocumentService(
    storage=minio_storage,
    store=rag_service.store,
    embedding=rag_service.embedding,
)

knowledge_service = KnowledgeService(
    embedding=rag_service.embedding,
    store=rag_service.store,
)

similar_document_service = SimilarDocumentService(
    embedding=rag_service.embedding,
    store=rag_service.store,
)

knowledge_quality_service = KnowledgeQualityService(
    similar_service=similar_document_service,
)

knowledge_graph_service = KnowledgeGraphService()

auth_service = AuthService()

audit_service = AuditService()

dashboard_service = DashboardService()

permission_service = PermissionService(
    store=rag_service.store,
)
