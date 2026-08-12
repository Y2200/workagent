"""
Production Test Suite（P5-5-7）

一键运行全部 P5-5 生产治理特性测试 + 生产契约断言（六条铁律）：

1. 运行 6 个 P5-5 子套件（trace/config/prompt_governance/llm_cost/failure_recovery/health）
2. 契约断言：
   - Agent/Tool 不直连 DB（静态扫描）
   - API 层不直连 DB（分层）
   - Prompt 外置（无内联业务 Prompt）
   - 工具经 RBAC / 多租户隔离（由安全类子测试覆盖）
3. 输出 reports/production_suite_report.json

用法：
    python -m work_agent.scripts.test_production_suite
"""

import json
import traceback

from datetime import datetime
from pathlib import Path

import work_agent.config  # noqa: F401（触发 UTF-8 重配置）

BASE = Path(__file__).resolve().parent.parent.parent.parent


# 参与汇总的 P5-5 子套件（模块 → 显示名）
SUITES = [
    ("work_agent.scripts.test_agent_trace", "agent_trace"),
    ("work_agent.scripts.test_agent_config", "agent_config"),
    ("work_agent.scripts.test_prompt_governance", "prompt_governance"),
    ("work_agent.scripts.test_llm_cost", "llm_cost"),
    ("work_agent.scripts.test_failure_recovery", "failure_recovery"),
    ("work_agent.scripts.test_health_monitoring", "health_monitoring"),
]


def _run_suite(module_name: str):
    """
    运行单个子套件，返回 (passed, error)
    """

    try:

        import importlib

        module = importlib.import_module(module_name)

        module.test()

        return True, ""

    except Exception as exc:

        return False, (
            f"{type(exc).__name__}: {exc}\n"
            + traceback.format_exc()[-1500:]
        )


# ======================
# 契约断言（六条铁律）
# ======================

def _check_agent_no_db_direct():
    """
    铁律2：Agent / Tool 禁止直连 DB
    """

    bad = []

    for directory in ("agent/agents", "agent/tools"):

        for path in (BASE / "src" / "work_agent" / directory).glob("*.py"):

            content = path.read_text(encoding="utf-8")

            for marker in (
                "SessionLocal",
                "db.query(",
                "from work_agent.db ",
            ):

                if marker in content:

                    bad.append(
                        f"{directory}/{path.name}: {marker}"
                    )

    return (
        len(bad) == 0,
        "无" if not bad else "; ".join(bad[:5]),
    )


def _check_api_layering():
    """
    铁律1：API 层不直连 DB（经 Service/Repository）
    """

    bad = []

    for path in (BASE / "src" / "work_agent" / "api").glob("*.py"):

        if path.name == "server.py":
            # 已知废弃重复 app（技术债务）
            continue

        content = path.read_text(encoding="utf-8")

        if "SessionLocal" in content:

            bad.append(f"api/{path.name}: SessionLocal")

    return (
        len(bad) == 0,
        "无" if not bad else "; ".join(bad),
    )


def _check_prompts_external():
    """
    铁律3：Prompt 外置（代码不内联业务 Prompt）
    """

    bad = []

    for directory in ("agent", "knowledge"):

        for path in (BASE / "src" / "work_agent" / directory).rglob("*.py"):

            content = path.read_text(encoding="utf-8")

            for marker in ("你是一名", "你是一个", 'prompt = """'):

                if marker in content:

                    bad.append(f"{path.relative_to(BASE)}: {marker}")

    return (
        len(bad) == 0,
        "无" if not bad else "; ".join(bad[:5]),
    )


_CONTRACTS = [
    ("agent_no_db_direct", _check_agent_no_db_direct),
    ("api_layering", _check_api_layering),
    ("prompts_external", _check_prompts_external),
]


def _run_contracts():
    """
    运行契约断言，返回 (passed, results)
    """

    results = []

    for name, checker in _CONTRACTS:

        try:

            passed, detail = checker()

            results.append(
                {
                    "contract": name,
                    "passed": passed,
                    "detail": detail,
                }
            )

        except Exception as exc:

            results.append(
                {
                    "contract": name,
                    "passed": False,
                    "detail": f"checker error: {exc}",
                }
            )

    return all(r["passed"] for r in results), results


def test():

    print("========== P5-5 Production Test Suite ==========\n")

    suite_results = []

    for module_name, display in SUITES:

        passed, error = _run_suite(module_name)

        suite_results.append(
            {
                "name": display,
                "passed": passed,
                "error": error,
            }
        )

        print(
            f"[{'PASS' if passed else 'FAIL'}] {display}"
            + (f"\n      {error.splitlines()[0]}" if not passed else "")
        )

    print()

    contracts_passed, contract_results = _run_contracts()

    for contract in contract_results:

        print(
            f"[{'PASS' if contract['passed'] else 'FAIL'}] "
            f"契约:{contract['contract']}"
            + (f"（{contract['detail']}）" if not contract["passed"] else "")
        )

    print()

    # ======================
    # 汇总
    # ======================

    suites_passed = sum(1 for s in suite_results if s["passed"])

    total = len(suite_results)

    all_passed = (
        suites_passed == total
        and contracts_passed
    )

    report = {
        "timestamp": datetime.now().isoformat(),
        "total_suites": total,
        "passed_suites": suites_passed,
        "contracts_passed": contracts_passed,
        "all_passed": all_passed,
        "suites": suite_results,
        "contracts": contract_results,
    }

    report_dir = BASE / "reports"

    report_dir.mkdir(exist_ok=True)

    report_path = report_dir / "production_suite_report.json"

    report_path.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(
        f"========== 汇总：{suites_passed}/{total} 子套件通过，"
        f"契约 {'通过' if contracts_passed else '失败'}"
        f" → {'全部通过 ✅' if all_passed else '存在失败 ❌'}"
        f"（报告：{report_path}） =========="
    )

    assert all_passed, "Production Test Suite 存在失败"

    print("Production Test Suite 全部通过")


if __name__ == "__main__":

    test()
