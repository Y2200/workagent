"""
多租户权限测试

前置：
    python -m work_agent.scripts.seed_tenants

场景1：企业A 财务员工 查询 财务报销制度 → 可召回
场景2：企业A 研发员工 查询 财务报销制度 → 被过滤
场景3：企业B 员工 查询企业A制度 → 0结果

用法：
    python -m work_agent.scripts.test_permission
"""

import time

from work_agent.core.container import document_service, rag_service
from work_agent.db.session import SessionLocal
from work_agent.repositories.document_repository import DocumentRepository
from work_agent.repositories.tenant_repository import TenantRepository
from work_agent.repositories.user_repository import UserRepository
from work_agent.scripts.seed_tenants import seed_tenants


def _wait_ready(
        document_id: int,
        timeout: float = 60.0
):

    repository = DocumentRepository()

    db = SessionLocal()

    try:

        start = time.time()

        while time.time() - start < timeout:

            # expire_all 清除身份映射缓存，确保读到最新状态
            db.expire_all()

            document = repository.get_by_id(
                db,
                document_id
            )

            if document and document.status in (
                    "ready",
                    "failed"
            ):
                return document.status

            time.sleep(1)

        return "timeout"

    finally:

        db.close()


def _upload_test_documents():

    """
    上传租户测试文档：
    企业A：财务报销制度（仅财务部可见）
    企业B：项目延期管理制度（公开）
    """

    db = SessionLocal()

    try:

        tenant_a_id = str(
            TenantRepository().get_by_corp_id(
                db,
                "ww_corp_A"
            ).id
        )

        tenant_b_id = str(
            TenantRepository().get_by_corp_id(
                db,
                "ww_corp_B"
            ).id
        )

    finally:

        db.close()

    # 企业A财务报销制度：仅财务部/财务人员可见（不含通用"员工"角色）
    doc_a = document_service.upload(
        filename="财务报销制度.md",
        data=(
            "财务报销制度：差旅报销需提交发票，"
            "超标需审批。"
        ).encode("utf-8"),
        category="财务管理",
        uploader="admin",
        tenant_id=tenant_a_id,
        visibility="restricted",
        departments=["财务部"],
        roles=["财务人员"]
    )

    # 企业B项目管理制度：公开
    doc_b = document_service.upload(
        filename="项目延期管理制度.md",
        data=(
            "项目延期管理制度：延期需提前报备，"
            "超期需上报负责人。"
        ).encode("utf-8"),
        category="项目管理",
        uploader="admin",
        tenant_id=tenant_b_id,
        visibility="public"
    )

    status_a = _wait_ready(doc_a.id)

    status_b = _wait_ready(doc_b.id)

    print(
        f"测试文档: 企业A财务报销制度(doc={doc_a.id})={status_a}, "
        f"企业B项目管理(doc={doc_b.id})={status_b}"
    )

    return doc_a.id, doc_b.id


def test():

    seed_tenants()

    _upload_test_documents()

    db = SessionLocal()

    try:

        user_repo = UserRepository()

        a_finance = user_repo.get_by_wechat_user_id(
            db,
            "wx_A_finance"
        )

        a_dev = user_repo.get_by_wechat_user_id(
            db,
            "wx_A_dev"
        )

        b_market = user_repo.get_by_wechat_user_id(
            db,
            "wx_B_market"
        )

    finally:

        db.close()

    # ======================
    # 场景1：企业A 财务员工 → 可召回
    # ======================

    r1 = rag_service.search(
        "财务报销制度是什么",
        top_k=5,
        user_context={
            "tenant_id": a_finance.tenant_id,
            "department": a_finance.department,
            "role": a_finance.role,
        }
    )

    s1_sources = [
        item["source"]
        for item in r1
    ]

    assert any(
        "财务报销制度" in source
        for source in s1_sources
    ), f"场景1失败: {s1_sources}"

    print(
        f"场景1 ✅ 企业A财务员工可召回: {s1_sources}"
    )

    # ======================
    # 场景2：企业A 研发员工 → 被过滤
    # ======================

    r2 = rag_service.search(
        "财务报销制度是什么",
        top_k=5,
        user_context={
            "tenant_id": a_dev.tenant_id,
            "department": a_dev.department,
            "role": a_dev.role,
        }
    )

    s2_sources = [
        item["source"]
        for item in r2
    ]

    assert not any(
        "财务报销制度" in source
        for source in s2_sources
    ), f"场景2失败: {s2_sources}"

    print(
        f"场景2 ✅ 企业A研发员工被过滤: {s2_sources or '无结果'}"
    )

    # ======================
    # 场景3：企业B 员工 → 0结果
    # ======================

    r3 = rag_service.search(
        "财务报销制度是什么",
        top_k=5,
        user_context={
            "tenant_id": b_market.tenant_id,
            "department": b_market.department,
            "role": b_market.role,
        }
    )

    s3_sources = [
        item["source"]
        for item in r3
    ]

    assert len(r3) == 0, f"场景3失败: {s3_sources}"

    print(
        f"场景3 ✅ 企业B员工检索企业A制度为0结果"
    )

    # 清理测试文档
    from work_agent.scripts.test_utils import cleanup_tenant_data

    cleanup_tenant_data()

    print("多租户权限测试全部通过")


if __name__ == "__main__":

    test()
