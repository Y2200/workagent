"""
Audit Logger 审计测试

场景1：企业A员工问答 → 生成 audit log，tenant_id 正确
场景2：企业B管理员 查日志 → 看不到企业A日志（租户隔离）
场景3：权限拒绝 → 产生 denied 日志
场景4：异常 → 产生 failed 日志

用法：
    python -m work_agent.scripts.test_audit
"""

import time

from pathlib import Path

from fastapi.testclient import TestClient

from work_agent.core.container import audit_service, document_service
from work_agent.db.models import AgentLog
from work_agent.db.session import SessionLocal
from work_agent.main import app
from work_agent.repositories.agent_log_repository import AgentLogRepository
from work_agent.repositories.document_repository import DocumentRepository
from work_agent.repositories.tenant_repository import TenantRepository
from work_agent.repositories.user_repository import UserRepository
from work_agent.scripts.seed_tenants import seed_tenants
from work_agent.wechat.service import process_message


def _tenant_id_by_corp(corp_id: str) -> str:

    db = SessionLocal()

    try:

        return str(
            TenantRepository().get_by_corp_id(
                db,
                corp_id
            ).id
        )

    finally:

        db.close()


def _user_by_wechat(wechat_id: str):

    db = SessionLocal()

    try:

        return UserRepository().get_by_wechat_user_id(
            db,
            wechat_id
        )

    finally:

        db.close()


def _wait_ready(
        document_id: int,
        timeout: float = 60.0
):

    repository = DocumentRepository()

    db = SessionLocal()

    try:

        start = time.time()

        while time.time() - start < timeout:

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


def _latest_log(
        tenant_id: str,
        user_id: int | None = None
):

    db = SessionLocal()

    try:

        logs = AgentLogRepository().list(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            limit=1,
        )

        return logs[0] if logs else None

    finally:

        db.close()


def _setup_documents() -> list[int]:

    tenant_a_id = _tenant_id_by_corp("ww_corp_A")

    tenant_b_id = _tenant_id_by_corp("ww_corp_B")

    finance_file = Path(
        "knowledge/财务报销制度.md"
    )

    project_file = Path(
        "knowledge/项目延期管理制度.md"
    )

    # 企业A财务报销制度：仅财务部/财务人员可见
    doc_a = document_service.upload(
        filename=finance_file.name,
        data=finance_file.read_bytes(),
        category="财务管理",
        uploader="admin_A",
        tenant_id=tenant_a_id,
        visibility="restricted",
        departments=["财务部"],
        roles=["财务人员"]
    )

    # 企业B项目管理制度：公开
    doc_b = document_service.upload(
        filename=project_file.name,
        data=project_file.read_bytes(),
        category="项目管理",
        uploader="admin_B",
        tenant_id=tenant_b_id,
        visibility="public"
    )

    _wait_ready(doc_a.id)

    _wait_ready(doc_b.id)

    print(
        f"测试文档: A财务报销(doc={doc_a.id}), B项目管理(doc={doc_b.id})"
    )

    return doc_a.id, doc_b.id


def test():

    seed_tenants()

    tenant_a_id = _tenant_id_by_corp("ww_corp_A")

    tenant_b_id = _tenant_id_by_corp("ww_corp_B")

    doc_a_id, doc_b_id = _setup_documents()

    a_finance = _user_by_wechat("wx_A_finance")

    a_dev = _user_by_wechat("wx_A_dev")

    b_market = _user_by_wechat("wx_B_market")

    # ======================
    # 场景1：企业A财务员工问答 → success 日志，tenant_id 正确
    # ======================

    process_message(
        {
            "user": "wx_A_finance",
            "content": "财务报销制度是什么",
        }
    )

    log1 = _latest_log(
        tenant_id=tenant_a_id,
        user_id=a_finance.id,
    )

    assert log1 is not None, "场景1失败: 未生成日志"

    assert log1.tenant_id == tenant_a_id, (
        f"场景1失败: tenant_id={log1.tenant_id}"
    )

    assert log1.status == "success", (
        f"场景1失败: status={log1.status}"
    )

    assert "财务报销制度" in log1.question, "场景1失败: 问题不一致"

    print(
        f"场景1 ✅ tenant_id={log1.tenant_id} status={log1.status} "
        f"intent={log1.intent} latency={log1.latency_ms}ms "
        f"tokens={log1.token_usage}"
    )

    # ======================
    # 场景3：企业A研发员工问答 → denied 日志
    # ======================

    process_message(
        {
            "user": "wx_A_dev",
            "content": "财务报销制度是什么",
        }
    )

    log3 = _latest_log(
        tenant_id=tenant_a_id,
        user_id=a_dev.id,
    )

    assert log3 is not None, "场景3失败: 未生成日志"

    assert log3.status == "denied", (
        f"场景3失败: status={log3.status}"
    )

    print(
        f"场景3 ✅ 权限拒绝 → denied (error={log3.error_type})"
    )

    # ======================
    # 场景2：企业B市场员工问答 → 企业B管理员看不到企业A日志
    # ======================

    process_message(
        {
            "user": "wx_B_market",
            "content": "项目延期管理制度是什么",
        }
    )

    # 直接服务层校验：企业B租户日志不含企业A日志
    page_b = audit_service.list_logs(
        tenant_id=tenant_b_id,
        page_size=50,
    )

    assert page_b["total"] >= 1, "场景2失败: 企业B应至少有1条日志"

    for item in page_b["items"]:
        assert item.tenant_id == tenant_b_id, (
            f"场景2失败: 混入企业A日志 tenant_id={item.tenant_id}"
        )

    print(f"场景2a ✅ 服务层租户隔离: 企业B日志{page_b['total']}条全为tenant {tenant_b_id}")

    # HTTP 层校验：admin_B 登录查询 /logs
    client = TestClient(app)

    resp = client.post(
        "/api/admin/auth/login",
        json={
            "username": "admin_B",
            "password": "test123"
        }
    )

    assert resp.status_code == 200, resp.text

    headers_b = {
        "Authorization": f"Bearer {resp.json()['access_token']}"
    }

    resp = client.get(
        "/api/admin/logs",
        headers=headers_b,
    )

    assert resp.status_code == 200, resp.text

    logs_b = resp.json()["items"]

    assert len(logs_b) > 0, "场景2b失败: admin_B 应看到企业B日志"

    for log in logs_b:
        assert log["tenant_id"] == tenant_b_id, (
            f"场景2b失败: admin_B 看到企业A日志 tenant_id={log['tenant_id']}"
        )

    print(f"场景2b ✅ HTTP层隔离: admin_B 只见tenant {tenant_b_id} 日志")

    # ======================
    # 场景4：异常 → failed 日志
    # ======================

    try:

        process_message(
            {
                "user": "wx_A_finance",
                "content": "",
            }
        )

        assert False, "场景4失败: 空内容应抛异常"

    except ValueError:
        pass

    db = SessionLocal()

    try:

        failed_log = (
            db.query(AgentLog)
            .filter(AgentLog.status == "failed")
            .order_by(AgentLog.id.desc())
            .first()
        )

    finally:

        db.close()

    assert failed_log is not None, "场景4失败: 未生成 failed 日志"

    assert failed_log.error_type == "ValueError", (
        f"场景4失败: error_type={failed_log.error_type}"
    )

    print(
        f"场景4 ✅ 异常 → failed (error_type={failed_log.error_type}, "
        f"error={failed_log.error_message[:30]})"
    )

    # ======================
    # 清理测试文档（按各自租户）
    # ======================

    document_service.delete(
        doc_a_id,
        tenant_id=_tenant_id_by_corp("ww_corp_A")
    )

    document_service.delete(
        doc_b_id,
        tenant_id=_tenant_id_by_corp("ww_corp_B")
    )

    print("审计测试全部通过")


if __name__ == "__main__":

    test()
