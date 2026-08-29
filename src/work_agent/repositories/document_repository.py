from sqlalchemy import func
from sqlalchemy.orm import Session

from work_agent.db.models import Document


class DocumentRepository:

    """
    文件数据访问
    """

    def create(
            self,
            db: Session,
            *,
            tenant_id: str,
            filename: str,
            file_type: str,
            storage_path: str,
            category: str,
            uploader: str,
            visibility: str = "public"
    ) -> Document:

        document = Document(
            tenant_id=tenant_id,
            filename=filename,
            file_type=file_type,
            storage_path=storage_path,
            category=category,
            uploader=uploader,
            visibility=visibility,
            status="processing"
        )

        db.add(document)

        db.commit()

        db.refresh(document)

        return document


    def get_by_id(
            self,
            db: Session,
            document_id: int
    ):

        return db.get(
            Document,
            document_id
        )


    def list(
            self,
            db: Session,
            tenant_id: str = "",
            status: str | None = None,
            offset: int = 0,
            limit: int = 100
    ):

        query = (
            db.query(Document)
            .filter(Document.tenant_id == tenant_id)
        )

        if status:
            query = query.filter(
                Document.status == status
            )

        return (
            query
            .order_by(Document.id.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )


    def update_visibility(
            self,
            db: Session,
            document_id: int,
            visibility: str
    ):

        document = db.get(
            Document,
            document_id
        )

        if not document:
            return None

        document.visibility = visibility

        db.add(document)

        db.commit()

        return document


    def update_category(
            self,
            db: Session,
            document_id: int,
            category: str
    ) -> bool:

        """
        更新文档分类（自动分类落库）

        category 为空时不更新，返回 False
        """

        if not category:
            return False

        document = db.get(
            Document,
            document_id
        )

        if not document:
            return False

        document.category = category

        db.add(document)

        db.commit()

        return True


    def update_status(
            self,
            db: Session,
            document_id: int,
            status: str,
            error_message: str | None = None
    ):

        document = db.get(
            Document,
            document_id
        )

        if not document:
            return None

        document.status = status

        document.error_message = error_message

        db.add(document)

        db.commit()

        return document


    def count_group_by_status(
            self,
            db: Session,
            tenant_id: str
    ) -> dict:

        """
        按状态统计文档数（租户隔离）
        """

        query = db.query(
            Document.status,
            func.count(Document.id)
        )

        if tenant_id is not None:
            query = query.filter(
                Document.tenant_id == tenant_id
            )

        rows = (
            query
            .group_by(Document.status)
            .all()
        )

        counts = {
            status: count
            for status, count in rows
        }

        return {
            "total": sum(counts.values()),
            "ready": counts.get("ready", 0),
            "processing": counts.get("processing", 0),
            "failed": counts.get("failed", 0),
        }


    def delete(
            self,
            db: Session,
            document_id: int
    ) -> bool:

        document = db.get(
            Document,
            document_id
        )

        if not document:
            return False

        db.delete(document)

        db.commit()

        return True
