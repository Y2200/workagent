"""
RAG 评测 CLI（手动完整评测，不硬断言，适合产出报告）

用法：
    python -m work_agent.scripts.run_rag_evaluation [--top-k 5] [--judge] [--chunk-experiment]

选项：
    --top-k N            评测使用 top_k（默认 5）
    --judge               额外做 LLM-as-judge 响应质量评分（烧 token，需 LLM key）
    --chunk-experiment    预留：chunk 大小对比实验（本轮未实现，列为 follow-up）

前提：依赖容器已起、库表已建（init_db / seed_tenants 会在脚本内执行）
"""

import argparse

from work_agent.db.session import SessionLocal
from work_agent.rag.evaluation import (
    DEFAULT_REPORT_PATH,
    cleanup,
    compute_metrics,
    generate_report,
    judge_cases,
    load_cases,
    run_case,
    setup,
    top_k_sweep,
)
from work_agent.repositories.tenant_repository import TenantRepository


def _tenant_id(corp_id: str) -> str:
    db = SessionLocal()
    try:
        return str(TenantRepository().get_by_corp_id(db, corp_id).id)
    finally:
        db.close()


def main():

    parser = argparse.ArgumentParser(
        description="RAG 检索评测（业务场景召回/响应质量）"
    )

    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="评测 top_k（默认 5）",
    )

    parser.add_argument(
        "--judge",
        action="store_true",
        help="LLM-as-judge 响应质量评分（烧 token）",
    )

    parser.add_argument(
        "--chunk-experiment",
        action="store_true",
        help="chunk 大小对比实验（本轮未实现，列为 follow-up）",
    )

    args = parser.parse_args()

    tenant_a = _tenant_id("ww_corp_A")

    tenant_b = _tenant_id("ww_corp_B")

    docs = setup(tenant_a, tenant_b)

    try:

        cases = load_cases()

        results = [
            run_case(c, args.top_k, tenant_a, tenant_b)
            for c in cases
        ]

        metrics = compute_metrics(results)

        sweep = top_k_sweep(cases, tenant_a, tenant_b)

        response_quality = None

        if args.judge:

            response_quality = judge_cases(
                cases,
                results,
                tenant_a,
                tenant_b,
            )

        if args.chunk_experiment:

            print(
                "⚠️ chunk 大小对比实验本轮未实现（绕管线直插需哨兵 document_id 清理，"
                "风险高），已列为 follow-up。"
            )

        generate_report(
            results,
            metrics,
            sweep=sweep,
            response_quality=response_quality,
            top_k=args.top_k,
        )

        print(
            f"评测完成: hit@k={metrics['hit_at_k']} recall@k={metrics['recall_at_k']} "
            f"mrr={metrics['mrr']} 权限拒={metrics['permission_deny_accuracy']} "
            f"租户隔离={metrics['tenant_isolation_accuracy']} "
            f"全局文档={metrics['global_doc_accuracy']}"
        )

        print(
            f"top_k sweep: k={[s['top_k'] for s in sweep]} "
            f"hit={[s['hit_at_k'] for s in sweep]}"
        )

        if response_quality:

            for q in response_quality:

                print(
                    f"judge {q['case_id']}: {q.get('judge_scores')} "
                    f"grounding={q.get('grounding_ok')}"
                )

        print(f"报告: {DEFAULT_REPORT_PATH}")

    finally:

        cleanup(docs)


if __name__ == "__main__":

    main()
