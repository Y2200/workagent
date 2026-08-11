import json

from collections import Counter
from pathlib import Path


# 数据集：src/work_agent/evaluation/datasets/agent_cases.json
DATASET_PATH = (
    Path(__file__).resolve().parents[2]
    / "evaluation"
    / "datasets"
    / "agent_cases.json"
)


class EvaluationDataset:

    """
    评测数据集加载
    """

    def __init__(
            self,
            path: str | None = None
    ):

        self.path = Path(
            path or DATASET_PATH
        )

        self.cases = self._load()


    def _load(self) -> list[dict]:

        if not self.path.exists():

            raise FileNotFoundError(
                f"评测数据集不存在: {self.path}"
            )

        with open(
                self.path,
                encoding="utf-8",
        ) as f:

            data = json.load(f)

        return data.get("cases", [])


    def get_cases(
            self,
            category: str | None = None,
            limit: int | None = None
    ) -> list[dict]:

        cases = self.cases

        if category:

            cases = [
                case
                for case in cases
                if case.get("category") == category
            ]

        if limit:

            cases = cases[:limit]

        return cases


    def categories(self) -> Counter:

        return Counter(
            case.get("category")
            for case in self.cases
        )


    @property
    def total(self) -> int:

        return len(self.cases)
