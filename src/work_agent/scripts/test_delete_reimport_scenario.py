"""
诊断实验：验证「上传 → 删除 → 导入多篇不同类型新文档 → 检索」场景（仅诊断，不改生产）

Part A  修复后行为验证：
    上传 3 篇不同类型制度（报销/网络安全/考勤）→ 基线全可检索
    → 删除报销 → 0 孤儿
    → 导入 同类型(新报销) + 不同类型(采购) → 逐一检索
    → 断言：新文档全部可检索（验证「全部查不到」在修复后不成立）

Part B  孤儿机制探针（模拟竞态残留，人工注入无主孤儿）：
    注入 6 条 document_id=无主哨兵 的报销类孤儿向量
    → 用报销 query 检索 top_k=5：同类型新报销是否被挤出？
    → 用采购/网络安全 query 检索：不同类型是否受影响？
    → 实证「召回污染(同类型)」 vs 「链路断裂(全部)」哪个成立

安全：文档用 PROBE* 前缀，finally 全量清理（文档 + 哨兵孤儿 + 租户数据）。
"""

import time

from work_agent.core.container import document_service, rag_service
from work_agent.db.session import SessionLocal
from work_agent.repositories.document_repository import DocumentRepository
from work_agent.repositories.tenant_repository import TenantRepository
from work_agent.scripts.seed_tenants import seed_tenants


TENANT = "1"

# 哨兵 document_id（无 PG 记录，仅用于模拟孤儿 + 精准清理）
ORPHAN_BASE = 990001

REIMBURSE_QUERY = "报销需要提交哪些发票和付款凭证？"
SECURITY_QUERY = "发现电脑中毒应该怎么处理？"
ATTEND_QUERY = "员工迟到多次会有什么处罚？"
PURCHASE_QUERY = "采购需要询价比价并签订采购合同吗？"

DOCS = {
    "PROBE报销.md": {
        "text": "# 财务报销制度\n一、报销流程\n员工填写报销单，粘贴发票和付款凭证，提交财务部审批，财务部确认后打款。\n二、报销标准\n差旅费、办公费凭发票报销，缺少发票和付款凭证不予受理。",
        "tenant": TENANT,
        "visibility": "restricted",
        "departments": ["财务部"],
        "query": REIMBURSE_QUERY,
        "dept": "财务部",
    },
    "PROBE网络安全.md": {
        "text": "# 网络安全管理制度\n一、终端安全\n办公电脑必须安装防病毒软件，发现中毒立即断网并上报安全负责人。\n二、应急响应\n安全事件发生后两小时内上报，按应急预案处理。",
        "tenant": TENANT,
        "visibility": "public",
        "departments": [],
        "query": SECURITY_QUERY,
        "dept": "研发部",
    },
    "PROBE考勤.md": {
        "text": "# 员工考勤管理制度\n一、考勤规则\n员工上下班需打卡，迟到三次口头警告，迟到五次扣绩效。\n二、请假衔接\n考勤异常须当日说明，无故迟到按旷工处理。",
        "tenant": TENANT,
        "visibility": "public",
        "departments": [],
        "query": ATTEND_QUERY,
        "dept": "研发部",
    },
    "PROBE新报销.md": {
        "text": "# 财务报销制度（修订版）\n一、报销流程\n员工填写报销单，粘贴发票和付款凭证，提交财务部审批，财务部复核后打款。\n二、报销时限\n每月25日前提交当月报销单。",
        "tenant": TENANT,
        "visibility": "restricted",
        "departments": ["财务部"],
        "query": REIMBURSE_QUERY,
        "dept": "财务部",
    },
    "PROBE采购.md": {
        "text": "# 采购审批制度\n一、采购流程\n填写采购申请单，采购部询价、比价，签订采购合同后付款，金额超五万需总经理审批。\n二、采购验收\n到货后组织验收，验收合格入库。",
        "tenant": TENANT,
        "visibility": "restricted",
        "departments": ["采购部"],
        "query": PURCHASE_QUERY,
        "dept": "采购部",
    },
}


def _tenant_id(corp_id: str) -> str:
    db = SessionLocal()
    try:
        return str(TenantRepository().get_by_corp_id(db, corp_id).id)
    finally:
        db.close()


def _wait_ready(document_id: int, timeout: float = 120.0) -> str:
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


def _upload(filename: str) -> int:
    spec = DOCS[filename]
    doc = document_service.upload(
        filename=filename,
        data=f"# {filename}\n\n{spec['text']}".encode("utf-8"),
        category="制度",
        uploader="probe",
        tenant_id=spec["tenant"],
        visibility=spec["visibility"],
        departments=spec["departments"],
        roles=[],
    )
    assert _wait_ready(doc.id) == "ready", f"{filename} 未就绪"
    return doc.id


def _search_sources(query: str, tenant: str, department: str, top_k: int = 5) -> list[str]:
    meta = rag_service.search_with_meta(
        query,
        top_k=top_k,
        user_context={
            "tenant_id": tenant,
            "department": department,
            "role": "员工",
        },
    )
    return [r.get("source", "") for r in meta["results"]]


def _inject_orphans(count: int = 6, tenant: str = "") -> None:
    """
    注入 count 条无主孤儿向量（document_id=哨兵，无 PG 记录）
    内容贴近报销 query，模拟"竞态残留的高相似度孤儿"
    """
    chunks = []
    for i in range(count):
        chunks.append({
            "text": f"报销需要提交哪些发票和付款凭证，报销单必须粘贴发票和付款凭证，缺少发票和付款凭证的报销单不予受理。发票付款凭证报销单{i}",
            "source": f"孤儿残留{i}.md",
            "metadata": {"access": {"departments": ["财务部"], "roles": [], "user_ids": []}},
        })
    rag_service.store.insert_documents(
        chunks,
        rag_service.embedding,
        document_id=ORPHAN_BASE + i,
        category="制度",
        tenant_id=tenant,
    )


def _count_orphans() -> int:
    total = 0
    for i in range(6):
        total += rag_service.store.count_by_document(ORPHAN_BASE + i)
    return total


def _purge() -> None:
    """彻底清理：哨兵孤儿 + 租户数据"""
    store = rag_service.store
    for i in range(6):
        try:
            store.delete_by_document(ORPHAN_BASE + i)
        except Exception:
            pass
    from work_agent.scripts.test_utils import cleanup_tenant_data
    cleanup_tenant_data(("1", "2"))


def test():

    seed_tenants()

    tenant = _tenant_id("ww_corp_A")

    _purge()

    try:
        print("== Part A：修复后行为验证 ==")

        # 1. 上传 3 篇不同类型 → 基线检索
        reimburse_id = _upload("PROBE报销.md")
        security_id = _upload("PROBE网络安全.md")
        attend_id = _upload("PROBE考勤.md")

        for fn, query in (
            ("PROBE报销.md", DOCS["PROBE报销.md"]["query"]),
            ("PROBE网络安全.md", DOCS["PROBE网络安全.md"]["query"]),
            ("PROBE考勤.md", DOCS["PROBE考勤.md"]["query"]),
        ):
            hits = _search_sources(query, tenant, DOCS[fn]["dept"])
            assert fn in hits, f"基线检索失败: {fn} → {hits}"
        print("✓ 基线：3 篇不同类型全部可检索")

        # 2. 删除报销 → 0 孤儿
        assert document_service.delete(reimburse_id, tenant_id=tenant)
        assert rag_service.store.count_by_document(reimburse_id) == 0, "删除后报销仍有向量"
        print("✓ 删除报销：0 孤儿向量")

        # 3. 再导入 同类型(新报销) + 不同类型(采购)
        new_reimburse_id = _upload("PROBE新报销.md")
        purchase_id = _upload("PROBE采购.md")

        hits = _search_sources(REIMBURSE_QUERY, tenant, "财务部")
        assert "PROBE新报销.md" in hits, f"删除后同类型新文档查不到: {hits}"
        print(f"✓ 删除后导入同类型新报销 → 可检索 (hits={hits[:3]})")

        hits = _search_sources(PURCHASE_QUERY, tenant, "采购部")
        assert "PROBE采购.md" in hits, f"删除后不同类型新文档查不到: {hits}"
        print(f"✓ 删除后导入不同类型采购 → 可检索 (hits={hits[:3]})")

        # 4. 仍能检索未被删的网络安全/考勤
        hits = _search_sources(SECURITY_QUERY, tenant, "研发部")
        assert "PROBE网络安全.md" in hits, f"网络安全受影响: {hits}"
        hits = _search_sources(ATTEND_QUERY, tenant, "研发部")
        assert "PROBE考勤.md" in hits, f"考勤受影响: {hits}"
        print("✓ 未被删除文档检索不受影响")

        print("== Part A 结论：修复后该场景不复发（删除→多篇不同类型新导入全部可检索） ==")

        print()
        print("== Part B：孤儿机制探针（人工注入竞态残留） ==")

        _inject_orphans(count=6, tenant=tenant)
        assert _count_orphans() == 6, "哨兵孤儿注入失败"
        print(f"✓ 已注入 6 条无主孤儿向量（document_id=哨兵 {ORPHAN_BASE}~+5）")

        # B1：同类型检索（报销）—— 孤儿是否把新报销挤出 top_k
        hits = _search_sources(REIMBURSE_QUERY, tenant, "财务部", top_k=5)
        reimburse_rank = hits.index("PROBE新报销.md") + 1 if "PROBE新报销.md" in hits else 0
        orphan_rank = next((i + 1 for i, h in enumerate(hits) if "孤儿残留" in h), 0)
        print(f"  报销检索 top5={hits}")
        print(f"  新报销 排名={reimburse_rank or '未命中(top5外)'}, 孤儿最高排名={orphan_rank or '未命中'}")

        # B2：不同类型检索（采购/网络安全）—— 是否受影响
        hits_purchase = _search_sources(PURCHASE_QUERY, tenant, "采购部", top_k=5)
        purchase_ok = "PROBE采购.md" in hits_purchase
        print(f"  采购检索 top5={hits_purchase} → 命中={purchase_ok}")

        hits_security = _search_sources(SECURITY_QUERY, tenant, "研发部", top_k=5)
        security_ok = "PROBE网络安全.md" in hits_security
        print(f"  网络安全检索 top5={hits_security} → 命中={security_ok}")

        print()
        print("== Part B 结论（实证） ==")
        print(f"  同类型新文档被孤儿挤出 top5: {reimburse_rank == 0}")
        print(f"  不同类型文档受影响: {not purchase_ok or not security_ok}")
        if reimburse_rank == 0:
            print("  → 孤儿会挤掉【同类型】新文档（召回空间污染）")
        if purchase_ok and security_ok:
            print("  → 孤儿不影响【不同类型】文档 → 「全部查不到」不能归因于孤儿挤占")
        print()

        print("诊断实验完成（Part A/B 均已执行，未修改任何生产代码）")

    finally:

        _purge()

        print("已清理：全部测试文档 + 哨兵孤儿向量")


if __name__ == "__main__":

    test()
