from sqlalchemy.orm import Session

from work_agent.db.models import DocumentPermission


class DocumentPermissionRepository:

    """
    文档权限数据访问

    public 文档：一条 department="ALL" 记录
    restricted 文档：每 department/role 一条记录
    """

    def bulk_create(
            self,
            db: Session,
            *,
            document_id: int,
            departments: list[str] | None = None,
            roles: list[str] | None = None,
            user_ids: list[int] | None = None,
            tenant_id: str = ""
    ) -> None:

        departments = departments or []

        roles = roles or []

        user_ids = user_ids or []

        if not departments and not roles and not user_ids:

            departments = ["ALL"]

        for department in departments:

            db.add(
                DocumentPermission(
                    tenant_id=tenant_id,
                    document_id=document_id,
                    department=department or "",
                    role=""
                )
            )

        for role in roles:

            db.add(
                DocumentPermission(
                    tenant_id=tenant_id,
                    document_id=document_id,
                    department="",
                    role=role
                )
            )

        for user_id in user_ids:

            db.add(
                DocumentPermission(
                    tenant_id=tenant_id,
                    document_id=document_id,
                    department="",
                    role="",
                    user_id=user_id
                )
            )

        db.commit()


    def get_by_document(
            self,
            db: Session,
            document_id: int
    ):

        return (
            db.query(DocumentPermission)
            .filter(DocumentPermission.document_id == document_id)
            .all()
        )


    def delete_by_document(
            self,
            db: Session,
            document_id: int
    ) -> None:

        db.query(DocumentPermission).filter(
            DocumentPermission.document_id == document_id
        ).delete(
            synchronize_session=False
        )

        db.commit()
