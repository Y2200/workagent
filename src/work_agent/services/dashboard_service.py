from datetime import datetime, time

from work_agent.config import settings
from work_agent.db.session import SessionLocal
from work_agent.repositories.agent_log_repository import AgentLogRepository
from work_agent.repositories.document_repository import DocumentRepository
from work_agent.repositories.tenant_repository import TenantRepository


class DashboardService:

    """
    管理驾驶舱统计（所有指标按租户隔离）
    """

    def __init__(
            self,
            document_repository: DocumentRepository | None = None,
            log_repository: AgentLogRepository | None = None,
            tenant_repository: TenantRepository | None = None
    ):

        self.document_repository = document_repository or DocumentRepository()

        self.log_repository = log_repository or AgentLogRepository()

        self.tenant_repository = tenant_repository or TenantRepository()


    def get_stats(
            self,
            tenant_id: str
    ) -> dict:

        """
        运营统计

        tenant_id 决定文档/问答/安全等数据范围
        tenant.total 为平台级租户总数（RBAC 上线后按角色裁剪）
        """

        # DB created_at 由 server_default=func.now() 生成（Postgres UTC）。
        # 时区对齐：today 边界用 UTC（同 cost_governance 既有修复），
        # 避免本地时区（UTC+8）凌晨时 date.today() 与 UTC 存储错位导致 today 计数为 0
        today_start = datetime.combine(
            datetime.utcnow().date(),
            time.min,
        )

        db = SessionLocal()

        try:

            documents = self.document_repository.count_group_by_status(
                db,
                tenant_id
            )

            qa = self.log_repository.today_stats(
                db,
                tenant_id,
                today_start
            )

            security = self.log_repository.security_counts(
                db,
                tenant_id
            )

            tenant_total = self.tenant_repository.count(
                db
            )

            tokens_today = qa["tokens_today"]

            estimated_cost = round(
                tokens_today
                / 1000
                * settings.model_cost_per_1k_tokens,
                4
            )

            return {
                "documents": documents,
                "qa": {
                    "today_count": qa["today_count"],
                    "success_rate": qa["success_rate"],
                    "avg_latency_ms": qa["avg_latency_ms"],
                    "avg_tokens": qa["avg_tokens"],
                },
                "security": security,
                "tenant": {
                    "total": tenant_total,
                },
                "usage": {
                    "tokens_today": tokens_today,
                    "estimated_cost": estimated_cost,
                },
            }

        finally:

            db.close()
