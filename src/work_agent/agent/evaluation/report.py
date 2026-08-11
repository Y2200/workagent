import json

from datetime import datetime
from pathlib import Path

from work_agent.config import BASE_DIR


DEFAULT_REPORT_PATH = (
    Path(BASE_DIR)
    / "reports"
    / "agent_eval_report.json"
)


def generate_report(
        results: list[dict],
        metrics: dict,
        output_path: str | None = None
) -> dict:

    """
    生成评测报告
    """

    path = Path(
        output_path or DEFAULT_REPORT_PATH
    )

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    report = {
        "timestamp":
            datetime.now().isoformat(),

        "total_cases":
            len(results),

        "passed":
            sum(
                1
                for result in results
                if result["passed"]
            ),

        "metrics":
            metrics,
    }

    with open(
            path,
            "w",
            encoding="utf-8",
    ) as f:

        json.dump(
            report,
            f,
            ensure_ascii=False,
            indent=2,
        )

    return report
