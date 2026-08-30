"""
RAG 检索评测测试（结合业务场景的召回效果量化评测）

覆盖：
- 业务场景 golden 集（normal / global_doc / permission_deny / cross_tenant，8 case）
- 指标：hit@k / recall@k / MRR / 权限拒正确率 / 租户隔离正确率 / 全局文档正确率
- 场景断言区分「权限拒」与「检索漏」（候选源集合证明）
- top_k 调优 sweep（3/5/8）
- 报告输出 reports/rag_eval_report.json

用法：
    python -m work_agent.scripts.test_rag_evaluation

前提：
- 依赖容器已起（docker compose up -d），库表已建（init_db）
- 独立运行需先 init_db；经 run_all_tests 运行时预初始化已就绪
"""

from work_agent.db.session import SessionLocal
from work_agent.rag.evaluation import (
    DEFAULT_REPORT_PATH,
    cleanup,
    compute_metrics,
    generate_report,
    load_cases,
    run_case,
    setup,
    top_k_sweep,
)
from work_agent.repositories.tenant_repository import TenantRepository
from work_agent.scripts.seed_tenants import seed_tenants


def _tenant_id(corp_id: str) -> str:
    db = SessionLocal()
    try:
        return str(TenantRepository().get_by_corp_id(db, corp_id).id)
    finally:
        db.close()


def test():

    seed_tenants()

    tenant_a = _tenant_id("ww_corp_A")

    tenant_b = _tenant_id("ww_corp_B")

    docs = setup(tenant_a, tenant_b)

    try:

        cases = load_cases()

        results = [
            run_case(c, c.get("top_k", 5), tenant_a, tenant_b)
            for c in cases
        ]

        metrics = compute_metrics(results)

        sweep = top_k_sweep(cases, tenant_a, tenant_b)

        generate_report(
            results,
            metrics,
            sweep=sweep,
            top_k=5,
        )

        # ======================
        # 断言（阈值与场景正确率）
        # ======================

        assert metrics["hit_at_k"] >= 0.8, metrics

        assert metrics["permission_deny_accuracy"] == 1.0, metrics

        assert metrics["tenant_isolation_accuracy"] == 1.0, metrics

        assert metrics["global_doc_accuracy"] == 1.0, metrics

        # ======================
        # 输出
        # ======================

        for r in results:

            mark = "✅" if r["passed"] else "❌"

            print(
                f"{mark} {r['case_id']} [{r['scenario']}] "
                f"query={r['query']} rank={r['rank_first_expected']} "
                f"candidates={r['candidates']} denied={r['denied']}"
            )

        print(
            f"检索评测: hit@k={metrics['hit_at_k']} recall@k={metrics['recall_at_k']} "
            f"mrr={metrics['mrr']} 权限拒={metrics['permission_deny_accuracy']} "
            f"租户隔离={metrics['tenant_isolation_accuracy']} "
            f"全局文档={metrics['global_doc_accuracy']}"
        )

        print(
            f"top_k sweep: "
            f"k={[s['top_k'] for s in sweep]} "
            f"hit={[s['hit_at_k'] for s in sweep]} "
            f"mrr={[s['mrr'] for s in sweep]}"
        )

        print(f"报告已生成: {DEFAULT_REPORT_PATH}")

        print("RAG 检索评测测试全部通过")

    finally:

        cleanup(docs)


if __name__ == "__main__":

    test()
