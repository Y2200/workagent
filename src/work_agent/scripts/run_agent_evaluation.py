"""
运行完整 Agent 评测并生成报告

用法：
    python -m work_agent.scripts.run_agent_evaluation [--limit N]
"""

import argparse

from work_agent.agent.evaluation.evaluator import Evaluator
from work_agent.agent.evaluation.metrics import Metrics
from work_agent.agent.evaluation.report import generate_report


def main():

    parser = argparse.ArgumentParser(
        description="Agent 评测"
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="每类用例数量（默认全部）",
    )

    args = parser.parse_args()

    evaluator = Evaluator()

    print("准备评测环境...")

    evaluator.setup()

    try:

        print("执行评测用例...")

        results = evaluator.run_all(
            limit=args.limit,
        )

        metrics = Metrics(
            results
        ).compute()

        report = generate_report(
            results,
            metrics,
        )

        print(
            f"\n评测完成: {report['total_cases']} 条，"
            f"通过 {report['passed']} 条"
        )

        for name, value in metrics.items():
            print(f"  {name}: {value}")

        print(
            f"\n报告已生成: "
            f"reports/agent_eval_report.json"
        )

        # 安全指标必须 100%
        if metrics["permission_safety_rate"] < 1.0:

            print("⚠️ 权限安全率未达 100%，请检查安全链路！")

        if metrics["tenant_isolation_rate"] < 1.0:

            print("⚠️ 租户隔离率未达 100%，请检查隔离链路！")

    finally:

        evaluator.cleanup()


if __name__ == "__main__":

    main()
