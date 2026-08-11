from sqlalchemy import func
from sqlalchemy.orm import Session

from work_agent.db.models import Tenant


class TenantRepository:

    """
    租户数据访问
    """

    def get_by_id(
            self,
            db: Session,
            tenant_id: int
    ):

        return db.get(
            Tenant,
            tenant_id
        )


    def get_by_corp_id(
            self,
            db: Session,
            corp_id: str
    ):

        return (
            db.query(Tenant)
            .filter(Tenant.corp_id == corp_id)
            .first()
        )


    def list(
            self,
            db: Session
    ):

        return (
            db.query(Tenant)
            .order_by(Tenant.id)
            .all()
        )


    def count(
            self,
            db: Session
    ) -> int:

        return int(
            db.query(func.count(Tenant.id)).scalar() or 0
        )


    def create(
            self,
            db: Session,
            *,
            name: str,
            corp_id: str,
            status: str = "active"
    ) -> Tenant:

        tenant = Tenant(
            name=name,
            corp_id=corp_id,
            status=status
        )

        db.add(tenant)

        db.commit()

        db.refresh(tenant)

        return tenant
