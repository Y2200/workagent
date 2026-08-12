import json
import re

from collections import Counter

from work_agent.config import settings
from work_agent.core.exceptions import TenantAccessDenied
from work_agent.core.prompt_manager import prompt_manager
from work_agent.db.session import SessionLocal
from work_agent.repositories.document_repository import DocumentRepository
from work_agent.repositories.knowledge_chunk_repository import KnowledgeChunkRepository
from work_agent.repositories.knowledge_graph_repository import (
    KnowledgeEntityRepository,
    KnowledgeRelationRepository,
)


# 确定性回退抽取时过滤的常见虚词/停用词
_STOPWORDS = {
    "我们", "他们", "可以", "需要", "进行", "一个", "没有", "就是",
    "这个", "那个", "以及", "相关", "有关", "根据", "对于", "如果",
    "但是", "因为", "所以", "其中", "以上", "以下", "如下", "不得",
    "应当", "必须", "本制度", "员工", "部门", "公司", "企业", "负责人",
}


class KnowledgeGraphService:

    """
    知识图谱服务

    build_for_document：按文档抽取实体/关系（LLM 优先，失败回退确定性高频词）
    build_all：批量重建某租户全部 ready 文档的图谱
    get_graph：返回节点 + 边（节点按名称跨文档合并，degree=关系度数）
    """

    def __init__(
            self,
            entity_repository: KnowledgeEntityRepository | None = None,
            relation_repository: KnowledgeRelationRepository | None = None,
            chunk_repository: KnowledgeChunkRepository | None = None,
            document_repository: DocumentRepository | None = None,
            llm=None
    ):

        self.entity_repository = (
            entity_repository or KnowledgeEntityRepository()
        )

        self.relation_repository = (
            relation_repository or KnowledgeRelationRepository()
        )

        self.chunk_repository = (
            chunk_repository or KnowledgeChunkRepository()
        )

        self.document_repository = (
            document_repository or DocumentRepository()
        )

        self.llm = llm


    def build_for_document(
            self,
            document_id: int,
            tenant_id: str
    ) -> dict:

        """
        重建单个文档的知识图谱（幂等）

        先删该文档旧关系 → 抽取实体/关系 → upsert 实体 → 写关系
        """

        db = SessionLocal()

        try:

            document = self.document_repository.get_by_id(
                db,
                document_id
            )

            if not document:
                raise ValueError(
                    f"文档不存在: {document_id}"
                )

            if document.tenant_id != tenant_id:
                raise TenantAccessDenied(
                    "无权构建该文档的知识图谱"
                )

            chunks = self.chunk_repository.get_by_document(
                db,
                document_id
            )

            if not chunks:
                return {
                    "document_id": document_id,
                    "entities": 0,
                    "relations": 0,
                    "fallback": False,
                }

            content = "\n".join(
                chunk.content
                for chunk in chunks
            )

            # 1. 清旧关系（重建幂等）
            self.relation_repository.delete_by_document(
                db,
                document_id
            )

            # 2. 抽取（LLM 优先，失败回退确定性）
            entities, relations, used_fallback = self._extract(
                title=document.filename,
                content=content,
            )

            entity_ids: dict[str, int] = {}

            for name, entity_type in entities:

                entity = self.entity_repository.get_or_create(
                    db,
                    tenant_id=tenant_id,
                    name=name,
                    entity_type=entity_type,
                )

                entity_ids[name] = entity.id

            created_relations = 0

            for source, target, relation in relations:

                source_id = entity_ids.get(source)
                target_id = entity_ids.get(target)

                # 跳过未识别实体与自环
                if not source_id or not target_id:
                    continue

                if source_id == target_id:
                    continue

                self.relation_repository.create(
                    db,
                    tenant_id=tenant_id,
                    document_id=document_id,
                    source_id=source_id,
                    target_id=target_id,
                    relation=relation,
                )

                created_relations += 1

            db.commit()

            return {
                "document_id": document_id,
                "entities": len(entities),
                "relations": created_relations,
                "fallback": used_fallback,
            }

        finally:

            db.close()


    def build_all(
            self,
            tenant_id: str
    ) -> dict:

        """
        批量重建某租户全部 ready 文档的知识图谱
        """

        db = SessionLocal()

        try:

            documents = self.document_repository.list(
                db,
                tenant_id=tenant_id,
                status="ready"
            )

        finally:

            db.close()

        results = []

        for document in documents:

            results.append(
                self.build_for_document(
                    document.id,
                    tenant_id,
                )
            )

        return {
            "built": len(results),
            "documents": results,
        }


    def get_graph(
            self,
            tenant_id: str
    ) -> dict:

        """
        返回某租户的知识图谱

        {
            "nodes": [{"id", "name", "type", "degree"}],
            "edges": [{"source", "target", "relation"}]
        }

        同名概念跨文档合并为单节点（入库时已按 name 去重）
        """

        db = SessionLocal()

        try:

            entities = self.entity_repository.list_by_tenant(
                db,
                tenant_id
            )

            relations = self.relation_repository.list_by_tenant(
                db,
                tenant_id
            )

        finally:

            db.close()

        degree: dict[int, int] = {}

        edges = []

        for rel in relations:

            degree[rel.source_id] = degree.get(
                rel.source_id,
                0
            ) + 1

            degree[rel.target_id] = degree.get(
                rel.target_id,
                0
            ) + 1

            edges.append(
                {
                    "source": rel.source_id,
                    "target": rel.target_id,
                    "relation": rel.relation,
                }
            )

        nodes = [
            {
                "id": entity.id,
                "name": entity.name,
                "type": entity.entity_type,
                "degree": degree.get(
                    entity.id,
                    0
                ),
            }
            for entity in entities
        ]

        return {
            "nodes": nodes,
            "edges": edges,
        }


    # ======================
    # 实体/关系抽取
    # ======================

    def _extract(
            self,
            *,
            title: str,
            content: str
    ) -> tuple[list, list, bool]:

        """
        抽取实体与关系

        返回：(entities[(name, type)], relations[(source, target, relation)], used_fallback)
        """

        try:

            entities, relations = self._extract_via_llm(
                title=title,
                content=content,
            )

            if entities:
                return entities, relations, False

        except Exception:

            pass

        entities, relations = self._extract_deterministic(
            content
        )

        return entities, relations, True


    def _extract_via_llm(
            self,
            *,
            title: str,
            content: str
    ) -> tuple[list, list]:

        loaded = prompt_manager.load(
            "kg_extract"
        )

        prompt = loaded["content"].format(
            title=title,
            content=content[:5000],
            entity_limit=settings.kg_entity_limit,
        )

        response = self._get_llm().invoke(
            prompt
        )

        data = self._parse_graph_json(
            response.content
        )

        entities = [
            (
                str(item.get("name", "")).strip()[:64],
                str(item.get("type", "概念")).strip()[:32] or "概念",
            )
            for item in data.get("entities", [])
            if str(item.get("name", "")).strip()
        ]

        relations = [
            (
                str(item.get("source", "")).strip(),
                str(item.get("target", "")).strip(),
                str(item.get("relation", "相关")).strip()[:64] or "相关",
            )
            for item in data.get("relations", [])
            if str(item.get("source", "")).strip()
            and str(item.get("target", "")).strip()
        ]

        return entities, relations


    @staticmethod
    def _parse_graph_json(text: str) -> dict:

        """
        从 LLM 输出解析图谱 JSON（兼容夹杂说明文字）
        """

        if not text:
            return {}

        match = re.search(
            r"\{.*\}",
            text,
            re.DOTALL,
        )

        if not match:
            return {}

        try:

            data = json.loads(
                match.group(0)
            )

            return data if isinstance(data, dict) else {}

        except json.JSONDecodeError:

            return {}


    def _extract_deterministic(
            self,
            content: str
    ) -> tuple[list, list]:

        """
        确定性回退：高频中文词组作实体，句内共现作"相关"关系

        保证无 LLM 时图谱仍非空
        """

        limit = max(
            settings.kg_entity_limit,
            1
        )

        tokens = [
            token
            for token in re.findall(
                r"[一-龥]{2,6}",
                content
            )
            if token not in _STOPWORDS
        ]

        top_names = [
            name
            for name, _ in Counter(tokens).most_common(
                limit
            )
        ]

        entities = [
            (name, "概念")
            for name in top_names
        ]

        # 句内共现关系
        sentences = re.split(
            r"[。！？!?；;\n]",
            content
        )

        relations = []

        for sentence in sentences:

            present = [
                name
                for name in top_names
                if name in sentence
            ]

            for i in range(len(present)):

                for j in range(i + 1, len(present)):

                    relations.append(
                        (present[i], present[j], "相关")
                    )

            if len(relations) >= limit:
                break

        return entities, relations


    def _get_llm(self):

        if self.llm:
            return self.llm

        from work_agent.agent.llm import get_llm

        self.llm = get_llm()

        return self.llm
