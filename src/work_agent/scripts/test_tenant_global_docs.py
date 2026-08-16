"""
租户语义测试：空租户文档全局可见（单企业一套知识库）

背景：Web 管理员（tenant_id=""）上传的文档是空租户；企微用户绑定具体租户（如 "1"）。
若检索仅按用户租户精确过滤，企微用户将检索不到 Web 上传的空租户文档（"Web能查、企微查不到"）。

修复：build_tenant_filter —— 空租户文档对所有用户全局可见 + 用户自己租户文档可见。
权限仍靠文档级 access（visibility/departments/roles/user_ids）控制，PermissionFilter 不受影响。

Part 1  空租户文档：企微用户（租户1）可检索
Part 2  非空租户隔离：企业B 员工仍看不到企业A 文档（租户边界不放松）
Part 3  权限过滤仍生效：无权限部门仍被 PermissionFilter 过滤
Part 4  build_tenant_filter 表达式正确性（单测）

用法：
    python -m work_agent.scripts.test_tenant_global_docs
"""

import time

from work_agent.core.container import document_service, rag_service
from work_agent.core.utils import build_tenant_filter
from work_agent.db.models import Document
from work_agent.db.session import SessionLocal
from work_agent.repositories.document_repository import DocumentRepository


TENANT_A = "1"
TENANT_B = "2"
WEB_TENANT = ""
MARK = "量子通信中继协议 TG-5566 加密标准AES-256-GCM"


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


def _upload(filename, text, tenant_id, category="制度"):
    return document_service.upload(
        filename=filename,
        data=f"# {filename}\n\n{text}".encode("utf-8"),
        category=category,
        uploader="admin",
        tenant_id=tenant_id,
    )


def _search(text, tenant_id, top_k=10):
    return rag_service.store.search_with_document(
        rag_service.embedding.encode([text])[0],
        top_k=top_k,
        score_threshold=0.0,
        filter=build_tenant_filter(tenant_id),
    )


def _cleanup():
    from work_agent.scripts.test_utils import cleanup_tenant_data
    cleanup_tenant_data(("1", "2"))
    # 清理空租户文档（测试自建）
    db = SessionLocal()
    try:
        docs = db.query(Document).filter(
            Document.tenant_id == ""
        ).all()
        for d in docs:
            document_service.delete(d.id, tenant_id="")
    finally:
        db.close()


def test_part1_empty_tenant_visible_to_all():
    """Part 1：空租户文档对具体租户用户全局可见"""
    doc = _upload("保密制度.md", MARK, WEB_TENANT)
    assert _wait_ready(doc.id) == "ready"

    # Web 管理员（空租户）可见
    hits_web = _search(MARK, WEB_TENANT)
    assert doc.id in {h.get("document_id") for h in hits_web}, "Web(空租户)应可见"

    # 企微用户（租户1）可见
    hits_wecom = _search(MARK, TENANT_A)
    assert doc.id in {h.get("document_id") for h in hits_wecom}, \
        f"企微(租户1)应可见空租户文档, 实际命中 {[h.get('document_id') for h in hits_wecom]}"
    print("✓ Part1 空租户文档对具体租户用户全局可见")


def test_part2_tenant_isolation_preserved():
    """Part 2：非空租户隔离不被破坏"""
    doc_a = _upload("A制度.md", "企业A独家内容 TA-1111", TENANT_A)
    assert _wait_ready(doc_a.id) == "ready"

    # 企业B 员工看不到企业A 文档
    hits_b = _search("企业A独家内容 TA-1111", TENANT_B)
    assert doc_a.id not in {h.get("document_id") for h in hits_b}, "企业B不应看到企业A文档"

    # 企业A 自己能看到
    hits_a = _search("企业A独家内容 TA-1111", TENANT_A)
    assert doc_a.id in {h.get("document_id") for h in hits_a}, "企业A应看到自己文档"
    print("✓ Part2 非空租户隔离保持（B 看不到 A）")


def test_part3_permission_filter_still_works():
    """Part 3：权限过滤仍生效（visibility 之外 access 元数据）"""
    # 公开空租户文档，但带受限 access（仅财务部）
    doc = document_service.upload(
        filename="受限制度.md",
        data=f"# 受限制度\n\n{MARK} 财务部专属 FL-8899".encode("utf-8"),
        category="制度",
        uploader="admin",
        tenant_id=WEB_TENANT,
        visibility="restricted",
        departments=["财务部"],
    )
    assert _wait_ready(doc.id) == "ready"

    # 财务部员工可检索（经 search_with_meta + PermissionFilter）
    meta = rag_service.search_with_meta(
        "财务部专属 FL-8899",
        top_k=5,
        user_context={
            "tenant_id": WEB_TENANT,
            "department": "财务部",
            "role": "员工",
        },
    )
    assert any(h.get("text", "").find("FL-8899") >= 0 for h in meta["results"]), \
        "财务部员工应可见受限文档"

    # 研发部员工被过滤（PermissionFilter）
    meta_rd = rag_service.search_with_meta(
        "财务部专属 FL-8899",
        top_k=5,
        user_context={
            "tenant_id": WEB_TENANT,
            "department": "研发部",
            "role": "员工",
        },
    )
    assert len(meta_rd["results"]) == 0, "研发部员工应被权限过滤"
    print("✓ Part3 文档级权限过滤仍生效（财务可见/研发被过滤）")


def test_part4_filter_expression():
    """Part 4：build_tenant_filter 表达式正确性"""
    assert build_tenant_filter("") == 'metadata["tenant_id"] == ""'
    assert (
        build_tenant_filter("1")
        == 'metadata["tenant_id"] == "1" or metadata["tenant_id"] == ""'
    )
    assert (
        build_tenant_filter("A&B")
        == 'metadata["tenant_id"] == "A&B" or metadata["tenant_id"] == ""'
    )
    print("✓ Part4 build_tenant_filter 表达式正确")


def test():
    print("== 租户语义测试（空租户全局可见）==")
    _cleanup()
    try:
        test_part4_filter_expression()
        test_part1_empty_tenant_visible_to_all()
        test_part2_tenant_isolation_preserved()
        test_part3_permission_filter_still_works()
    finally:
        _cleanup()
    print("租户语义测试全部通过")


if __name__ == "__main__":
    test()
