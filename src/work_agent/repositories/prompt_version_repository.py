from datetime import datetime

from sqlalchemy.orm import Session

from work_agent.db.models import PromptVersion


class PromptVersionRepository:

    """
    Prompt 版本数据访问
    """

    def create(
            self,
            db: Session,
            *,
            tenant_id: str,
            name: str,
            version: str,
            content: str,
            status: str,
            variables: list | None,
            description: str,
            updated_by: str
    ) -> PromptVersion:

        row = PromptVersion(
            tenant_id=tenant_id,
            name=name,
            version=version,
            content=content,
            status=status,
            variables=variables,
            description=description,
            updated_by=updated_by,
        )

        db.add(row)

        db.commit()

        db.refresh(row)

        return row


    def get_by_name_version(
            self,
            db: Session,
            *,
            tenant_id: str,
            name: str,
            version: str
    ) -> PromptVersion | None:

        return (
            db.query(PromptVersion)
            .filter(
                PromptVersion.tenant_id == tenant_id,
                PromptVersion.name == name,
                PromptVersion.version == version,
            )
            .first()
        )


    def get_active(
            self,
            db: Session,
            *,
            tenant_id: str,
            name: str
    ) -> PromptVersion | None:

        return (
            db.query(PromptVersion)
            .filter(
                PromptVersion.tenant_id == tenant_id,
                PromptVersion.name == name,
                PromptVersion.status == "active",
            )
            .first()
        )


    def list_by_name(
            self,
            db: Session,
            *,
            tenant_id: str,
            name: str
    ) -> list[PromptVersion]:

        return (
            db.query(PromptVersion)
            .filter(
                PromptVersion.tenant_id == tenant_id,
                PromptVersion.name == name,
            )
            .order_by(PromptVersion.id.desc())
            .all()
        )


    def list_names(
            self,
            db: Session,
            *,
            tenant_id: str
    ) -> list[str]:

        rows = (
            db.query(PromptVersion.name)
            .filter(PromptVersion.tenant_id == tenant_id)
            .distinct()
            .all()
        )

        return [
            name
            for (name,) in rows
        ]


    def set_status(
            self,
            db: Session,
            row: PromptVersion,
            status: str
    ) -> None:

        row.status = status

        db.add(row)

        db.commit()


    def deactivate_others(
            self,
            db: Session,
            *,
            tenant_id: str,
            name: str,
            except_version: str
    ) -> int:

        """
        将同名的其他版本标记为非 active
        """

        result = (
            db.query(PromptVersion)
            .filter(
                PromptVersion.tenant_id == tenant_id,
                PromptVersion.name == name,
                PromptVersion.version != except_version,
                PromptVersion.status == "active",
            )
            .update(
                {"status": "deprecated"},
                synchronize_session=False,
            )
        )

        db.commit()

        return int(result or 0)
