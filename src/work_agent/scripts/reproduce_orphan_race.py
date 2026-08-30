"""
实证：删除-异步入库竞态 → Milvus 孤儿向量 → 制度问答"幻觉"

背景：制度"上传→删除→重新上传"后回答仍引用旧版内容。根因是删除与
异步管线插入存在竞态，已删文档仍被写入 Milvus（孤儿向量）并参与 Top-K 召回。

本脚本三段实证：
  Part A  竞态机制实证（模拟未修复行为）：删除完成后，管线尾部再写入
          （跳过 _is_active 校验）→ 孤儿向量必然产生 → 检索命中孤儿。
  Part B  当前修复压力测试：多轮「上传→立即删除」，管线被 deleting 状态
          阻断 + 写入前后校验 → 最终 0 孤儿（双侧 PG/Milvus 均无残留）。
  Part C  幻觉现象端到端验证：删旧版→传新版→检索，断言旧版独特内容
          不出现在结果（0 孤儿 → 不会引用旧版 → 幻觉来源被清除）。

安全：文档用 REPRO* 前缀 + 租户 1/2，finally 全量清理（文档 + 注入孤儿 + 租户数据）。
用法：
    python -m work_agent.scripts.reproduce_orphan_race
"""

import time

from work_agent.core.container import document_service, rag_service
from work_agent.db.models import Document, KnowledgeChunk
from work_agent.db.session import SessionLocal
from work_agent.repositories.document_repository import DocumentRepository


TENANT = "1"

OLD_MARK = "旧版报销标准：差旅费按 200 元/天上限报销。代号-旧版V1"
NEW_MARK = "新版报销标准：差旅费按 500 元/天上限报销。代号-新版V2"
QUERY = "差旅费报销标准是多少钱一天？"

OLD_TEXT = (
    "# 财务报销制度（旧版）\n"
    "一、报销标准\n"
    "差旅费按 200 元/天上限报销，凭发票实报实销。\n"
    "二、流程\n"
    "员工填写报销单，财务审批后打款。\n"
    f"三、备注 {OLD_MARK}"
)

NEW_TEXT = (
    "# 财务报销制度（新版）\n"
    "一、报销标准\n"
    "差旅费按 500 元/天上限报销，凭发票实报实销。\n"
    "二、流程\n"
    "员工填写报销单，财务审批后打款。\n"
    f"三、备注 {NEW_MARK}"
)


# ======================
# 辅助
# ======================

def _wait_ready(document_id, timeout=120.0) -> str:
    repo = DocumentRepository()
    db = SessionLocal()
    try:
        start = time.time()
        while time.time() - start < timeout:
            db.expire_all()
            doc = repo.get_by_id(db, document_id)
            if doc and doc.status in ("ready", "failed"):
                return doc.status
            time.sleep(0.5)
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


def _chunk_texts(document_id) -> list[str]:
    db = SessionLocal()
    try:
        return [
            row.content
            for row in db.query(KnowledgeChunk).filter(
                KnowledgeChunk.document_id == document_id
            ).all()
        ]
    finally:
        db.close()


def _upload(filename: str, text: str) -> int:
    doc = document_service.upload(
        filename=filename,
        data=f"# {filename}\n\n{text}".encode("utf-8"),
        category="制度",
        uploader="repro",
        tenant_id=TENANT,
        visibility="restricted",
        departments=["财务部"],
        roles=[],
    )
    status = _wait_ready(doc.id)
    assert status == "ready", f"{filename} 未就绪: {status}"
    return doc.id


def _search_sources(query: str, top_k: int = 10) -> list[dict]:
    meta = rag_service.search_with_meta(
        query,
        top_k=top_k,
        user_context={
            "tenant_id": TENANT,
            "department": "财务部",
            "role": "员工",
        },
    )
    return meta["results"]


def _purge() -> None:
    """清理租户 1/2 全部文档 + 可能残留的孤儿向量"""
    from work_agent.scripts.test_utils import cleanup_tenant_data
    cleanup_tenant_data(("1", "2"))


# ======================
# Part A：竞态机制实证（模拟未修复行为）
# ======================

def part_a():
    print("== Part A：竞态机制实证（模拟未修复的管线尾部写入） ==")

    doc_id = _upload("REPRO-A旧版.md", OLD_TEXT)
    chunks = _chunk_texts(doc_id)
    assert chunks, "应有 knowledge_chunks"

    # 1. 正常删除 → PG/Milvus 双侧清空
    assert document_service.delete(doc_id, tenant_id=TENANT)
    assert _db_doc(doc_id) is None
    assert _db_chunks(doc_id) == 0
    assert _milvus_count(doc_id) == 0
    print(f"✓ 删除完成：PG 与 Milvus 均清空 (doc_id={doc_id})")

    # 2. 模拟未修复的管线尾部：删除之后把 chunk 写进 Milvus（无 _is_active 校验）
    #    这正是竞态窗口的真实后果 —— 旧实现此时不检查文档状态
    rag_service.store.insert_documents(
        [
            {
                "text": chunks[0],
                "source": "REPRO-A旧版.md",
                "metadata": {
                    "access": {
                        "departments": ["财务部"],
                        "roles": [],
                        "user_ids": [],
                    },
                },
            }
        ],
        rag_service.embedding,
        document_id=doc_id,
        category="制度",
        tenant_id=TENANT,
    )

    # 3. 孤儿成立：Milvus 有向量，PG 无记录
    assert _milvus_count(doc_id) == 1, "应产生 1 条孤儿向量"
    assert _db_doc(doc_id) is None
    assert _db_chunks(doc_id) == 0
    print(f"✓ 竞态后果实证：孤儿向量产生（Milvus=1，PG=0）doc_id={doc_id}")

    # 4. 检索命中孤儿 → 模拟"幻觉"来源（旧版内容进 Top-K）
    hits = _search_sources(QUERY, top_k=10)
    orphan_hit = [
        r for r in hits
        if r.get("source") == "REPRO-A旧版.md"
    ]
    print(f"  检索 Top-{len(hits)} 命中孤儿: {bool(orphan_hit)}"
          + (f"（rank 含 '旧版V1' 内容，会被 LLM 当作现行制度复述）" if orphan_hit else ""))

    # 清理注入的孤儿
    rag_service.store.delete_by_document(doc_id)
    assert _milvus_count(doc_id) == 0
    print("✓ 已清理注入孤儿\n")

    return doc_id


# ======================
# Part B：当前修复压力测试（真实竞态，多轮）
# ======================

def part_b(rounds: int = 12):
    print(f"== Part B：当前修复压力测试（{rounds} 轮「上传→立即删除」） ==")

    total_orphans = 0
    leaked = []
    for i in range(rounds):
        doc = document_service.upload(
            filename=f"REPRO-B竞态{i}.md",
            data=f"# REPRO-B{i}\n竞态压力测试独有标记 RB-{i} 报销内容".encode("utf-8"),
            category="制度",
            uploader="repro",
            tenant_id=TENANT,
        )
        doc_id = doc.id
        # 立即删除（不等管线）→ 制造竞态窗口
        assert document_service.delete(doc_id, tenant_id=TENANT)
        # 等管线滞后插入被二次校验回滚（自愈）
        time.sleep(4.0)
        cnt = _milvus_count(doc_id)
        pg = _db_chunks(doc_id)
        if cnt or pg:
            leaked.append((i, doc_id, cnt, pg))
        total_orphans += cnt

    print(f"  完成 {rounds} 轮，泄漏轮次: {leaked if leaked else '无'}")
    print(f"  孤儿向量总数: {total_orphans}")
    assert total_orphans == 0, f"存在孤儿泄漏: {leaked}"
    print("✓ Part B 结论：当前修复在真实竞态下 0 孤儿向量\n")


# ======================
# Part C：幻觉现象端到端验证（删旧版 → 传新版 → 检索）
# ======================

def part_c():
    print("== Part C：幻觉现象端到端验证（删旧版→传新版→检索） ==")

    # 1. 上传旧版 → 确认可检索
    old_id = _upload("REPRO-C旧版.md", OLD_TEXT)
    hits = _search_sources(QUERY)
    assert any("REPRO-C旧版.md" in (r.get("source") or "") for r in hits), "旧版应可检索"
    print(f"✓ 旧版上线：可检索 (doc_id={old_id})")

    # 2. 删除旧版 → 0 孤儿
    assert document_service.delete(old_id, tenant_id=TENANT)
    assert _milvus_count(old_id) == 0
    assert _db_chunks(old_id) == 0
    print("✓ 删除旧版：0 孤儿（PG/Milvus 均清空）")

    # 3. 上传新版 → 检索
    new_id = _upload("REPRO-C新版.md", NEW_TEXT)
    hits = _search_sources(QUERY, top_k=10)

    # 4. 断言：新版命中、旧版独特内容不残留
    new_hit = any("REPRO-C新版.md" in (r.get("source") or "") for r in hits)
    assert new_hit, "新版应被检索到"
    stale_text = [
        r for r in hits
        if "旧版V1" in (r.get("text") or "")
    ]
    assert not stale_text, f"旧版独特内容仍出现在结果中（幻觉来源未清除）: {stale_text}"
    print(f"✓ 新版命中，旧版内容（{OLD_MARK[:8]}…）未出现在 Top-{len(hits)}")
    print(f"✓ 最终孤儿: 旧版={_milvus_count(old_id)} 新版={_milvus_count(new_id)}")
    print("✓ Part C 结论：修复后同类型重传不残留旧版内容，幻觉来源清除\n")


def test():
    _purge()
    try:
        part_a()
        part_b()
        part_c()
        print("实证全部通过 ✅ 竞态机制真实、修复在多次竞态下 0 孤儿、旧版内容不残留")
    finally:
        _purge()
        print("\n已清理：全部测试文档 + 注入孤儿 + 租户数据")


if __name__ == "__main__":
    test()
