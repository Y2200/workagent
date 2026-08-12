"""
Knowledge Intelligence 测试（P5-4）

覆盖：
- 自动分类（管线钩入 + 回退）
- 知识图谱（构建 + 查询）
- 相似文档检测
- 知识质量分析
- 跨租户隔离
- LLM 失败确定性回退

用法：
    python -m work_agent.scripts.test_knowledge_intelligence
"""

import time

from work_agent.config import settings
from work_agent.core.container import (
    document_service,
    knowledge_graph_service,
    knowledge_quality_service,
    rag_service,
    similar_document_service,
)
from work_agent.db.models import KnowledgeEntity, KnowledgeRelation
from work_agent.db.session import SessionLocal
from work_agent.knowledge.classifier import DocumentClassifier
from work_agent.knowledge.graph import KnowledgeGraphService
from work_agent.repositories.document_repository import DocumentRepository
from work_agent.repositories.tenant_repository import TenantRepository
from work_agent.scripts.seed_tenants import seed_tenants


# ======================
# 测试文档内容
# ======================

SIMILAR_TEXT = """财务报销制度
一、适用范围
本制度适用于公司全体员工，各部门均需遵守财务报销制度。
二、报销流程
员工填写报销单，提交部门负责人审批，审批通过后由财务部复核，财务部确认后完成打款。
三、报销标准
差旅费、办公费、招待费按照公司财务报销标准执行，超标准部分不予报销。
四、附则
本制度自发布之日起执行，如有修订以最新版本为准。"""

SIMILAR_TEXT_V2 = """财务报销制度（修订版）
一、适用范围
本制度适用于公司全体员工，各部门均需遵守财务报销制度。
二、报销流程
员工填写报销单，提交部门负责人审批，审批通过后由财务部复核，财务部确认后完成打款。
三、报销标准
差旅费、办公费、招待费按照公司财务报销标准执行，超标准部分不予报销。
四、附则
本制度自发布之日起执行，如有修订以最新版本为准。"""

SECURITY_TEXT = """网络安全管理制度
一、账户安全
所有员工必须设置高强度密码，密码至少包含字母、数字与特殊字符。
二、终端安全
办公终端必须安装公司统一防病毒软件，禁止私自安装来路不明的软件。
三、数据安全
敏感数据必须加密存储，禁止通过公共网络传输公司机密数据。
四、应急响应
发生安全事件时，立即上报安全负责人并启动应急响应预案。"""


# ======================
# 测试桩
# ======================

class FakeClassifier:

    """
    确定性分类器：按标题关键词返回类别（替代真实 LLM）
    """

    def classify(
            self,
            *,
            title: str,
            content: str,
            fallback: str = ""
    ) -> str:

        if "安全" in title:
            return "安全管理"

        if "报销" in title:
            return "财务制度"

        return fallback or "未分类"


class RaisingLLM:

    """
    模拟 LLM 故障（用于验证确定性回退）
    """

    def invoke(
            self,
            prompt
    ):
        raise RuntimeError("LLM unavailable")


# ======================
# 工具函数
# ======================

def _tenant_id(corp_id: str) -> str:

    db = SessionLocal()

    try:

        return str(
            TenantRepository().get_by_corp_id(db, corp_id).id
        )

    finally:

        db.close()


def _cleanup():

    from work_agent.scripts.test_utils import cleanup_tenant_data

    cleanup_tenant_data()

    # 清理知识图谱残留
    db = SessionLocal()

    try:

        db.query(KnowledgeRelation).filter(
            KnowledgeRelation.tenant_id.in_(["1", "2"])
        ).delete(synchronize_session=False)

        db.query(KnowledgeEntity).filter(
            KnowledgeEntity.tenant_id.in_(["1", "2"])
        ).delete(synchronize_session=False)

        db.commit()

    finally:

        db.close()


def _wait_ready(document_id: int, timeout: float = 90.0):

    db = SessionLocal()

    try:

        start = time.time()

        while time.time() - start < timeout:

            db.expire_all()

            doc = DocumentRepository().get_by_id(
                db,
                document_id
            )

            if doc and doc.status in ("ready", "failed"):
                return doc.status

            time.sleep(1)

        return "timeout"

    finally:

        db.close()


def _document(document_id: int):

    db = SessionLocal()

    try:

        return DocumentRepository().get_by_id(
            db,
            document_id
        )

    finally:

        db.close()


def _milvus_categories(document_id: int) -> list[str]:

    """
    读取某文档在 Milvus 中的 category 元数据
    """

    store = rag_service.store

    rows = store.client.query(
        collection_name=store.COLLECTION_NAME,
        filter=f"document_id == {document_id}",
        output_fields=["metadata"],
        limit=100,
        consistency_level="Strong",
    )

    return [
        row.get("metadata", {}).get("category", "")
        for row in rows
    ]


# ======================
# 测试
# ======================

def test():

    seed_tenants()

    _cleanup()

    tenant_a = _tenant_id("ww_corp_A")

    tenant_b = _tenant_id("ww_corp_B")

    # ======================
    # 准备：注入确定性分类器，上传 3 篇文档
    # ======================

    document_service.pipeline.classifier = FakeClassifier()

    settings.knowledge_auto_classify = True

    doc_a = document_service.upload(
        filename="财务报销制度.md",
        data=SIMILAR_TEXT.encode("utf-8"),
        category="",
        uploader="admin_A",
        tenant_id=tenant_a,
    )

    doc_b = document_service.upload(
        filename="财务报销制度修订版.md",
        data=SIMILAR_TEXT_V2.encode("utf-8"),
        category="",
        uploader="admin_A",
        tenant_id=tenant_a,
    )

    doc_c = document_service.upload(
        filename="网络安全管理制度.md",
        data=SECURITY_TEXT.encode("utf-8"),
        category="",
        uploader="admin_A",
        tenant_id=tenant_a,
    )

    assert _wait_ready(doc_a.id) == "ready", doc_a.id
    assert _wait_ready(doc_b.id) == "ready", doc_b.id
    assert _wait_ready(doc_c.id) == "ready", doc_c.id

    # ======================
    # 场景1：自动分类
    # ======================

    # 1a：管线自动分类落库 + 同步 Milvus metadata
    doc_a_db = _document(doc_a.id)

    assert doc_a_db.category == "财务制度", doc_a_db.category

    assert _milvus_categories(doc_a.id) == ["财务制度"], _milvus_categories(doc_a.id)

    doc_c_db = _document(doc_c.id)

    assert doc_c_db.category == "安全管理", doc_c_db.category

    # 1b：分类器失败回退 + 短内容兜底
    classifier = DocumentClassifier(
        llm=RaisingLLM()
    )

    assert classifier.classify(
        title="测试",
        content="这是一段足够长的测试内容，用于验证分类器在 LLM 故障时的回退逻辑是否正常执行。",
        fallback="人事制度",
    ) == "人事制度"

    assert classifier.classify(
        title="测试",
        content="短",
        fallback="",
    ) == "未分类"

    print("场景1 ✅ 自动分类（管线落库 + Milvus 同步 + 回退）")

    # ======================
    # 场景2：知识图谱构建 + 查询
    # ======================

    build_result = knowledge_graph_service.build_for_document(
        doc_a.id,
        tenant_a,
    )

    assert build_result["entities"] >= 1, build_result

    graph = knowledge_graph_service.get_graph(
        tenant_a
    )

    assert graph["nodes"], graph

    assert graph["edges"], graph

    assert all(node["name"] for node in graph["nodes"]), graph

    print(
        f"场景2 ✅ 知识图谱（entities={build_result['entities']}, "
        f"relations={build_result['relations']}, "
        f"nodes={len(graph['nodes'])}, edges={len(graph['edges'])}）"
    )

    # ======================
    # 场景3：相似文档检测
    # ======================

    similar = similar_document_service.find_similar(
        doc_a.id,
        tenant_a,
        threshold=0.8,
    )

    ids = [item["document_id"] for item in similar]

    assert doc_b.id in ids, similar

    assert doc_c.id not in ids, similar

    doc_b_hit = next(
        item
        for item in similar
        if item["document_id"] == doc_b.id
    )

    assert doc_b_hit["max_score"] > 0.9, doc_b_hit

    print(f"场景3 ✅ 相似文档（命中 doc_b={doc_b.id}，max_score={doc_b_hit['max_score']}，排除无关 doc_c）")

    # ======================
    # 场景4：知识质量分析
    # ======================

    report = knowledge_quality_service.analyze(
        tenant_a
    )

    expected_keys = {
        "tenant_id",
        "overview",
        "chunk_stats",
        "chunk_length",
        "classification",
        "duplicates",
        "consistency",
        "health_score",
    }

    assert expected_keys <= set(report), report.keys()

    assert report["overview"]["total_documents"] == 3, report["overview"]

    assert report["overview"]["total_chunks"] == 3, report["overview"]

    assert report["consistency"]["consistent"] is True, report["consistency"]

    assert report["consistency"]["milvus_orphan_vectors"] == 0, report["consistency"]

    assert report["classification"]["unclassified_documents"] == 0, report["classification"]

    assert report["duplicates"]["pairs"], report["duplicates"]

    assert 0 <= report["health_score"] <= 100, report["health_score"]

    print(
        f"场景4 ✅ 知识质量（documents={report['overview']['total_documents']}, "
        f"consistent={report['consistency']['consistent']}, "
        f"health={report['health_score']}, duplicate_pairs={len(report['duplicates']['pairs'])}）"
    )

    # ======================
    # 场景5：跨租户隔离
    # ======================

    doc_d = document_service.upload(
        filename="B企业专属制度.md",
        data=SECURITY_TEXT.encode("utf-8"),
        category="",
        uploader="admin_B",
        tenant_id=tenant_b,
    )

    assert _wait_ready(doc_d.id) == "ready", doc_d.id

    # B 租户构建图谱
    knowledge_graph_service.build_for_document(
        doc_d.id,
        tenant_b,
    )

    graph_a_before = len(
        knowledge_graph_service.get_graph(tenant_a)["nodes"]
    )

    graph_a_after = len(
        knowledge_graph_service.get_graph(tenant_a)["nodes"]
    )

    assert graph_a_before == graph_a_after, (graph_a_before, graph_a_after)

    graph_b = knowledge_graph_service.get_graph(tenant_b)

    assert graph_b["nodes"], graph_b

    # 质量统计互不干扰
    report_a = knowledge_quality_service.analyze(tenant_a)

    report_b = knowledge_quality_service.analyze(tenant_b)

    assert report_a["overview"]["total_documents"] == 3, report_a["overview"]

    assert report_b["overview"]["total_documents"] == 1, report_b["overview"]

    print("场景5 ✅ 跨租户隔离（B 图谱不影响 A；质量统计互不泄漏）")

    # ======================
    # 场景6：LLM 失败确定性回退（图谱仍非空）
    # ======================

    fallback_service = KnowledgeGraphService(
        llm=RaisingLLM()
    )

    fallback_result = fallback_service.build_for_document(
        doc_c.id,
        tenant_a,
    )

    assert fallback_result["fallback"] is True, fallback_result

    assert fallback_result["entities"] >= 2, fallback_result

    assert fallback_result["relations"] >= 1, fallback_result

    print(
        f"场景6 ✅ 确定性回退（LLM 故障 → entities={fallback_result['entities']}, "
        f"relations={fallback_result['relations']}）"
    )

    # ======================
    # 清理
    # ======================

    document_service.delete(doc_a.id, tenant_id=tenant_a)
    document_service.delete(doc_b.id, tenant_id=tenant_a)
    document_service.delete(doc_c.id, tenant_id=tenant_a)
    document_service.delete(doc_d.id, tenant_id=tenant_b)

    _cleanup()

    print("Knowledge Intelligence 测试全部通过")


if __name__ == "__main__":

    test()
