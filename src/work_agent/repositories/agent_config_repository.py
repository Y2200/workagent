from sqlalchemy.orm import Session

from work_agent.db.models import AgentConfig


class AgentConfigRepository:

    """
    Agent 配置数据访问
    """

    def get(
            self,
            db: Session,
            *,
            tenant_id: str,
            config_key: str
    ) -> AgentConfig | None:

        return (
            db.query(AgentConfig)
            .filter(
                AgentConfig.tenant_id == tenant_id,
                AgentConfig.config_key == config_key,
            )
            .first()
        )


    def upsert(
            self,
            db: Session,
            *,
            tenant_id: str,
            config_key: str,
            config_value,
            description: str = "",
            updated_by: str = ""
    ) -> AgentConfig:

        """
        创建或更新配置项（按 tenant + key）
        """

        row = self.get(
            db,
            tenant_id=tenant_id,
            config_key=config_key,
        )

        if row:

            row.config_value = config_value

            row.description = description

            row.updated_by = updated_by

            db.add(row)

        else:

            row = AgentConfig(
                tenant_id=tenant_id,
                config_key=config_key,
                config_value=config_value,
                description=description,
                updated_by=updated_by,
            )

            db.add(row)

        db.commit()

        db.refresh(row)

        return row


    def list_by_tenant(
            self,
            db: Session,
            tenant_id: str
    ) -> list[AgentConfig]:

        return (
            db.query(AgentConfig)
            .filter(AgentConfig.tenant_id == tenant_id)
            .order_by(AgentConfig.config_key)
            .all()
        )


    def list_platform(
            self,
            db: Session
    ) -> list[AgentConfig]:

        return (
            db.query(AgentConfig)
            .filter(AgentConfig.tenant_id == "")
            .order_by(AgentConfig.config_key)
            .all()
        )
