import time

from pathlib import Path

from work_agent.agent.evaluation.dataset import EvaluationDataset
from work_agent.agent.runtime import agent_runtime
from work_agent.db.session import SessionLocal
from work_agent.repositories.document_repository import DocumentRepository
from work_agent.repositories.tenant_repository import TenantRepository
from work_agent.repositories.user_repository import UserRepository


class Evaluator:

    """
    评测执行器

    每个 case 通过 AgentRuntime.execute() 执行（不绕过 Agent）
    """

    def __init__(
            self,
            dataset: EvaluationDataset | None = None,
            runtime=None
    ):

        self.dataset = dataset or EvaluationDataset()

        self.runtime = runtime or agent_runtime

        self._setup_state = None


    def setup(self) -> None:

        """
        准备评测环境：租户 + RBAC + 测试文档
        """

        from work_agent.scripts.seed_rbac import seed_rbac
        from work_agent.scripts.seed_tenants import seed_tenants
        from work_agent.scripts.test_utils import cleanup_tenant_data
        from work_agent.core.container import document_service

        seed_tenants()

        seed_rbac()

        cleanup_tenant_data()

        tenant_a_id = self._tenant_id("ww_corp_A")

        tenant_b_id = self._tenant_id("ww_corp_B")

        # 租户A受限文档
        doc_a = document_service.upload(
            filename="财务报销制度.md",
            data=Path("knowledge/财务报销制度.md").read_bytes(),
            category="财务管理",
            uploader="admin_A",
            tenant_id=tenant_a_id,
            visibility="restricted",
            departments=["财务部"],
            roles=["财务人员"],
        )

        # 租户B公开文档（租户隔离评测用）
        doc_b = document_service.upload(
            filename="企业B专属机密制度.md",
            data="企业B专属机密制度内容，仅企业B可见".encode("utf-8"),
            category="测试",
            uploader="admin_B",
            tenant_id=tenant_b_id,
            visibility="public",
        )

        self._wait_ready(doc_a.id)

        self._wait_ready(doc_b.id)

        self._setup_state = {
            "tenant_a_id": tenant_a_id,
            "tenant_b_id": tenant_b_id,
            "doc_a_id": doc_a.id,
            "doc_b_id": doc_b.id,
        }


    def cleanup(self) -> None:

        from work_agent.core.container import document_service
        from work_agent.scripts.test_utils import cleanup_tenant_data

        if self._setup_state:

            document_service.delete(
                self._setup_state["doc_a_id"],
                tenant_id=self._setup_state["tenant_a_id"],
            )

            document_service.delete(
                self._setup_state["doc_b_id"],
                tenant_id=self._setup_state["tenant_b_id"],
            )

            self._setup_state = None

        cleanup_tenant_data()


    def run_case(
            self,
            case: dict
    ) -> dict:

        """
        执行单个评测用例
        """

        user = self._get_user(
            case.get("user", "员工A")
        )

        input_text = self._resolve(
            case.get("input", "")
        )

        result = self.runtime.execute(
            message=input_text,
            user=user,
            channel="eval",
        )

        passed, check = self._check(
            case,
            result,
        )

        return {
            "case_id": case.get("id", ""),
            "category": case.get("category", ""),
            "check": check,
            "passed": passed,
            "detail": {
                "intent": result.get("intent", ""),
                "agent": result.get("agent", ""),
                "tools_called": result.get("tools_called", []),
                "permission_denied": result.get("permission_denied", False),
            },
        }


    def run_all(
            self,
            categories: list[str] | None = None,
            limit: int | None = None
    ) -> list[dict]:

        """
        执行全部评测用例
        """

        categories = categories or [
            "intent",
            "tool",
            "agent",
            "security",
            "regression",
        ]

        cases = []

        for category in categories:

            cases.extend(
                self.dataset.get_cases(
                    category=category,
                    limit=limit,
                )
            )

        results = []

        for case in cases:

            try:

                results.append(
                    self.run_case(case)
                )

            except Exception as exc:

                # 单 case 异常不中断整体评测
                results.append(
                    {
                        "case_id": case.get("id", ""),
                        "category": case.get("category", ""),
                        "check": "error",
                        "passed": False,
                        "detail": {
                            "error": str(exc),
                            "error_type": type(exc).__name__,
                        },
                    }
                )

        return results


    def _check(
            self,
            case: dict,
            result: dict
    ) -> tuple[bool, str]:

        category = case.get("category", "")

        if category == "intent":

            expected = case.get(
                "expected_intent"
            )

            return (
                result.get("intent") == expected,
                "intent",
            )

        if category == "tool":

            expected = case.get(
                "expected_tool",
                "",
            )

            parts = expected.split(".")

            expected_tool = parts[0]

            expected_action = (
                parts[1]
                if len(parts) > 1
                else ""
            )

            calls = result.get(
                "tool_calls",
                [],
            )

            ok = any(
                call.get("tool") == expected_tool
                and call.get("action") == expected_action
                for call in calls
            )

            return ok, "tool"

        if category == "agent":

            return (
                result.get("agent")
                == case.get("expected_agent"),
                "agent",
            )

        if category == "security":

            expected = case.get("expected")

            if expected == "permission_denied":

                return (
                    result.get("permission_denied")
                    is True,
                    "permission_denied",
                )

            if expected == "not_leaked":

                marker = case.get(
                    "not_leaked",
                    "",
                )

                return (
                    marker
                    not in result.get(
                        "response",
                        "",
                    ),
                    "tenant_isolation",
                )

            return False, "security"

        if category == "regression":

            return (
                bool(result.get("response")),
                "regression",
            )

        return False, "unknown"


    def _resolve(self, text: str) -> str:

        """
        替换动态占位符（文档ID）
        """

        state = self._setup_state or {}

        return (
            text
            .replace(
                "{DOC_A}",
                str(state.get("doc_a_id", "")),
            )
            .replace(
                "{DOC_B}",
                str(state.get("doc_b_id", "")),
            )
        )


    @staticmethod
    def _tenant_id(corp_id: str) -> str:

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


    @staticmethod
    def _get_user(username: str):

        db = SessionLocal()

        try:

            return UserRepository().get_by_username(
                db,
                username
            )

        finally:

            db.close()


    @staticmethod
    def _wait_ready(
            document_id: int,
            timeout: float = 60.0
    ):

        db = SessionLocal()

        try:

            start = time.time()

            while time.time() - start < timeout:

                db.expire_all()

                doc = DocumentRepository().get_by_id(
                    db,
                    document_id
                )

                if doc and doc.status in (
                        "ready",
                        "failed"
                ):
                    return doc.status

                time.sleep(1)

            return "timeout"

        finally:

            db.close()
