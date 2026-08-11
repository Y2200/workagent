"""
Agent 评测系统测试（P5-3）

场景1：评测数据加载
场景2：Intent 评测
场景3：Tool 评测
场景4：Agent 路由评测
场景5：安全评测（权限拒绝 + 租户隔离）
场景6：报告生成

用法：
    python -m work_agent.scripts.test_agent_evaluation
"""

from work_agent.agent.evaluation.dataset import EvaluationDataset
from work_agent.agent.evaluation.evaluator import Evaluator
from work_agent.agent.evaluation.metrics import Metrics
from work_agent.agent.evaluation.report import generate_report


def test():

    dataset = EvaluationDataset()

    # ======================
    # 场景1：评测数据加载
    # ======================

    assert dataset.total == 50, f"应 50 条: {dataset.total}"

    categories = dataset.categories()

    assert all(
        categories[cat] == 10
        for cat in ("intent", "tool", "agent", "security", "regression")
    ), categories

    print(
        f"场景1 ✅ 数据加载: {dataset.total} 条, "
        f"分布={dict(categories)}"
    )

    # ======================
    # 场景2-4：Intent / Tool / Agent 评测（子样本）
    # ======================

    evaluator = Evaluator()

    evaluator.setup()

    try:

        batch_results = evaluator.run_all(
            categories=["intent", "tool", "agent"],
            limit=2,
        )

        metrics = Metrics(batch_results).compute()

        assert 0.0 <= metrics["intent_accuracy"] <= 1.0, metrics

        assert 0.0 <= metrics["tool_accuracy"] <= 1.0, metrics

        assert 0.0 <= metrics["agent_routing_accuracy"] <= 1.0, metrics

        print(
            f"场景2-4 ✅ 评测执行: intent={metrics['intent_accuracy']}, "
            f"tool={metrics['tool_accuracy']}, "
            f"agent={metrics['agent_routing_accuracy']}"
        )

        # ======================
        # 场景5：安全评测（权限拒绝 + 租户隔离）
        # ======================

        security_cases = [
            case
            for case in dataset.get_cases(category="security")
            if case["id"] in ("security_001", "security_006")
        ]

        security_results = [
            evaluator.run_case(case)
            for case in security_cases
        ]

        security_metrics = Metrics(security_results).compute()

        # 权限拒绝必须通过
        assert security_metrics["permission_safety_rate"] == 1.0, security_metrics

        # 租户隔离必须通过
        assert security_metrics["tenant_isolation_rate"] == 1.0, security_metrics

        print(
            f"场景5 ✅ 安全评测: permission_safety={security_metrics['permission_safety_rate']}, "
            f"tenant_isolation={security_metrics['tenant_isolation_rate']}"
        )

        # ======================
        # 场景6：报告生成
        # ======================

        all_results = batch_results + security_results

        all_metrics = Metrics(all_results).compute()

        report = generate_report(
            all_results,
            all_metrics,
        )

        from pathlib import Path

        from work_agent.config import BASE_DIR

        report_path = (
            Path(BASE_DIR)
            / "reports"
            / "agent_eval_report.json"
        )

        assert report_path.exists(), "报告文件应生成"

        assert report["total_cases"] == len(all_results), report

        assert "metrics" in report, report

        print(
            f"场景6 ✅ 报告生成: {report_path.name}, "
            f"total={report['total_cases']}, passed={report['passed']}"
        )

    finally:

        evaluator.cleanup()

    print("Agent 评测系统测试全部通过")


if __name__ == "__main__":

    test()
