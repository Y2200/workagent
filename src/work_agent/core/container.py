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
from work_agent.services.trace_service import TraceService
from work_agent.services.config_service import agent_config_service
from work_agent.services.prompt_governance_service import prompt_governance_service
from work_agent.services.cost_governance_service import cost_governance_service
from work_agent.services.health_service import health_service
from work_agent.services.task_service import task_service
from work_agent.services.notification_service import notification_service
from work_agent.services.task_reminder_service import task_reminder_service


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

trace_service = TraceService()

# Agent 配置中心单例（services/config_service.py 内定义）
agent_config_service = agent_config_service

# Prompt 治理单例 + 注册 resolver 到 PromptManager
prompt_governance_service = prompt_governance_service
prompt_governance_service.register_resolver()

# LLM 成本治理单例
cost_governance_service = cost_governance_service

# 健康监控单例
health_service = health_service

# 任务督导单例（services/task_service.py 内定义）
task_service = task_service

# 统一通知单例（services/notification_service.py 内定义）
notification_service = notification_service

# 任务自动督办单例（services/task_reminder_service.py 内定义，Phase 3）
task_reminder_service = task_reminder_service
