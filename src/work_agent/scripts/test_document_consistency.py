"""
文档 PG/Milvus 一致性测试（修复删除-管线竞态）

背景：Web 上传后文档以 processing 状态立即出现，管线在后台线程异步执行。
若用户在管线完成前删除文档，原实现会产生 Milvus 孤儿向量
（PG documents/knowledge_chunks 已删，Milvus 向量残留），
后续搜索被孤儿污染，新文档可能被挤出 top_k —— 用户报告"删除后新导入查不到"。

修复：删除先标记 deleting → 管线在插入 Milvus 前后各校验一次文档状态，
被删则跳过插入 / 回滚已插入向量。

Part 1  顺序删除彻底（删除后 PG/Milvus 均无残留）
Part 2  删除后新导入可检索（正常路径不回归）
Part 3  竞态删除最终一致性（删除→管线滞后插入→二次校验回滚→最终 0 孤儿）

用法：
    python -m work_agent.scripts.test_document_consistency
"""

import time

from work_agent.core.container import document_service, rag_service
from work_agent.db.models import Document, KnowledgeChunk
from work_agent.db.session import SessionLocal
from work_agent.repositories.document_repository import DocumentRepository


TENANT = "1"
MARK_A = "一致性测试甲乙方保密条款代号 AA-101"
MARK_B = "一致性测试新材料独特内容代号 BB-202"


def _wait_ready(document_id, timeout=120.0):
    repo = DocumentRepository()
    db = SessionLocal()
    try:
        start = time.time()
        while time.time() - start < timeout:
            db.expire_all()
            doc = repo.get_by_id(db, document_id)
            if doc and doc.status in ("ready", "failed"):
                return doc.status
            time.sleep(1)
        return "timeout"
    finally:
        db.close()


def _db_chunks(document_id) -> int:
    db = SessionLocal()
    try:
        return db.query(KnowledgeChunk).filter(
            KnowledgeChunk.document_id == document_id
        ).count()
    finally:
        db.close()


def _db_doc(document_id):
    db = SessionLocal()
    try:
        return db.query(Document).filter(
            Document.id == document_id
        ).first()
    finally:
        db.close()


def _milvus_count(document_id) -> int:
    return rag_service.store.count_by_document(document_id)


def _search(text):
    hits = rag_service.store.search_with_document(
        rag_service.embedding.encode([text])[0],
        top_k=10,
        score_threshold=0.0,
        filter=f'metadata["tenant_id"] == "{TENANT}"',
    )
    return {h.get("document_id") for h in hits}


def _upload(text, filename):
    return document_service.upload(
        filename=filename,
        data=f"# {filename}\n\n{text}".encode("utf-8"),
        category="制度",
        uploader="admin",
        tenant_id=TENANT,
    )


def _cleanup():
    from work_agent.scripts.test_utils import cleanup_tenant_data
    cleanup_tenant_data(("1", "2"))


def test_part1_ordered_delete_thorough():
    """Part 1：顺序删除后 PG 与 Milvus 均无残留"""
    doc = _upload(MARK_A, "材料A.md")
    assert _wait_ready(doc.id) == "ready"

    ok = document_service.delete(doc.id, tenant_id=TENANT)
    assert ok

    assert _db_doc(doc.id) is None, "PG documents 残留"
    assert _db_chunks(doc.id) == 0, "PG knowledge_chunks 残留"
    assert _milvus_count(doc.id) == 0, "Milvus 向量残留"
    print("✓ Part1 顺序删除彻底：PG + Milvus 均清空")


def test_part2_reimport_searchable():
    """Part 2：删除后新导入文档可检索（正常路径）"""
    doc_a = _upload(MARK_A, "材料A.md")
    assert _wait_ready(doc_a.id) == "ready"
    document_service.delete(doc_a.id, tenant_id=TENANT)

    doc_b = _upload(MARK_B, "材料B.md")
    assert _wait_ready(doc_b.id) == "ready"

    hit_ids = _search(MARK_B)
    assert doc_b.id in hit_ids, f"新文档 id={doc_b.id} 未命中: {hit_ids}"
    print("✓ Part2 删除后新导入可检索")


def test_part3_race_final_consistency():
    """Part 3：竞态删除（上传后立即删）最终无孤儿向量"""
    orphan_total = 0
    # 与 errors.txt 原始记录一致：竞态复现 8 轮最终 0 孤儿
    rounds = 8
    for i in range(rounds):
        doc = _upload(
            f"竞态材料{i} 独有标记 RC-{200+i}",
            f"竞态{i}.md",
        )
        ok = document_service.delete(doc.id, tenant_id=TENANT)
        assert ok
        # 等待管线滞后插入被二次校验回滚（自愈）
        time.sleep(4.0)
        cnt = _milvus_count(doc.id)
        assert cnt == 0, (
            f"round{i}: 文档 {doc.id} 删除后 Milvus 残留 {cnt} 条孤儿向量"
        )
        orphan_total += cnt
    assert orphan_total == 0
    print(f"✓ Part3 竞态删除 {rounds} 轮：最终 0 孤儿向量")


def test():
    print("== 文档 PG/Milvus 一致性测试 ==")
    _cleanup()
    try:
        test_part1_ordered_delete_thorough()
        test_part2_reimport_searchable()
        test_part3_race_final_consistency()
    finally:
        _cleanup()
    print("文档一致性测试全部通过")


if __name__ == "__main__":
    test()
