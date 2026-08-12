from sqlalchemy.orm import Session

from work_agent.db.models import KnowledgeEntity, KnowledgeRelation


class KnowledgeEntityRepository:

    """
    知识图谱实体数据访问
    """

    def get_or_create(
            self,
            db: Session,
            *,
            tenant_id: str,
            name: str,
            entity_type: str = "概念"
    ) -> KnowledgeEntity:

        """
        按 (tenant_id, name) 查找，不存在则创建

        同名概念跨文档合并为同一节点
        """

        entity = (
            db.query(KnowledgeEntity)
            .filter(
                KnowledgeEntity.tenant_id == tenant_id,
                KnowledgeEntity.name == name,
            )
            .first()
        )

        if entity:
            return entity

        entity = KnowledgeEntity(
            tenant_id=tenant_id,
            name=name,
            entity_type=entity_type,
        )

        db.add(entity)

        db.flush()

        return entity


    def list_by_tenant(
            self,
            db: Session,
            tenant_id: str
    ) -> list[KnowledgeEntity]:

        return (
            db.query(KnowledgeEntity)
            .filter(KnowledgeEntity.tenant_id == tenant_id)
            .order_by(KnowledgeEntity.id)
            .all()
        )


    def count_by_tenant(
            self,
            db: Session,
            tenant_id: str
    ) -> int:

        return (
            db.query(KnowledgeEntity)
            .filter(KnowledgeEntity.tenant_id == tenant_id)
            .count()
        )


class KnowledgeRelationRepository:

    """
    知识图谱关系数据访问
    """

    def create(
            self,
            db: Session,
            *,
            tenant_id: str,
            document_id: int,
            source_id: int,
            target_id: int,
            relation: str = "相关"
    ) -> KnowledgeRelation:

        rel = KnowledgeRelation(
            tenant_id=tenant_id,
            document_id=document_id,
            source_id=source_id,
            target_id=target_id,
            relation=relation,
        )

        db.add(rel)

        db.flush()

        return rel


    def delete_by_document(
            self,
            db: Session,
            document_id: int
    ) -> int:

        count = (
            db.query(KnowledgeRelation)
            .filter(KnowledgeRelation.document_id == document_id)
            .delete(
                synchronize_session=False
            )
        )

        return count


    def delete_by_tenant(
            self,
            db: Session,
            tenant_id: str
    ) -> int:

        count = (
            db.query(KnowledgeRelation)
            .filter(KnowledgeRelation.tenant_id == tenant_id)
            .delete(
                synchronize_session=False
            )
        )

        return count


    def list_by_tenant(
            self,
            db: Session,
            tenant_id: str
    ) -> list[KnowledgeRelation]:

        return (
            db.query(KnowledgeRelation)
            .filter(KnowledgeRelation.tenant_id == tenant_id)
            .all()
        )
