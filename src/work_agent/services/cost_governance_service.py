"""
LLM 成本治理

- 按租户记账 token/成本
- 月度预算限额（存于配置中心 cost.monthly_budget）
- 超限拦截（check_quota）
- 用量分析（今日/本月，按模型/用户）
"""

from datetime import date, datetime, time

from work_agent.config import settings
from work_agent.db.session import SessionLocal
from work_agent.repositories.llm_cost_repository import LLMCostRepository
from work_agent.services.config_service import agent_config_service


class CostGovernanceService:

    """
    LLM 成本治理服务
    """

    def __init__(
            self,
            repository: LLMCostRepository | None = None,
            config_service=None
    ):

        self.repository = repository or LLMCostRepository()

        self.config_service = config_service


    def record(
            self,
            *,
            tenant_id: str,
            request_id: str,
            user_id: int | None = None,
            model: str = "",
            input_tokens: int = 0,
            output_tokens: int = 0,
            total_tokens: int | None = None
    ) -> None:

        """
        记账一笔 LLM 成本

        total_tokens 缺省 = input + output
        """

        total = (
            total_tokens
            if total_tokens is not None
            else input_tokens + output_tokens
        )

        cost = round(
            total
            / 1000
            * settings.model_cost_per_1k_tokens,
            6,
        )

        db = SessionLocal()

        try:

            self.repository.create(
                db,
                tenant_id=tenant_id,
                request_id=request_id,
                user_id=user_id,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total,
                cost=cost,
            )

        finally:

            db.close()


    def get_budget(
            self,
            tenant_id: str
    ) -> float | None:

        """
        月度预算（元）；None = 不限制
        """

        config_service = self._get_config_service()

        if config_service is None:
            return None

        value = config_service.get(
            "cost.monthly_budget",
            tenant_id,
        )

        if value is None:
            return None

        try:
            return float(value)
        except (TypeError, ValueError):
            return None


    def set_budget(
            self,
            *,
            tenant_id: str,
            budget: float | None,
            updated_by: str = ""
    ) -> None:

        """
        设置月度预算（None = 不限制）
        """

        config_service = self._get_config_service()

        if config_service is None:
            return

        config_service.set(
            key="cost.monthly_budget",
            value=budget,
            tenant_id=tenant_id,
            updated_by=updated_by,
        )


    def check_quota(
            self,
            tenant_id: str
    ) -> dict:

        """
        校验某租户是否还有预算额度

        budget=None → 不限制，始终 allowed
        """

        budget = self.get_budget(tenant_id)

        spent = self._month_spend(tenant_id)

        if budget is None:

            return {
                "allowed": True,
                "budget": None,
                "spent": spent,
                "remaining": None,
            }

        return {
            "allowed": spent < budget,
            "budget": round(budget, 4),
            "spent": spent,
            "remaining": round(
                max(budget - spent, 0.0),
                4,
            ),
        }


    def usage(
            self,
            tenant_id: str
    ) -> dict:

        """
        用量分析：今日 + 本月（按模型/用户）
        """

        now = datetime.now()

        today_start = datetime.combine(
            date.today(),
            time.min,
        )

        month_start = datetime(
            now.year,
            now.month,
            1,
        )

        db = SessionLocal()

        try:

            today = self.repository.sum_by_period(
                db,
                tenant_id=tenant_id,
                since=today_start,
            )

            month = self.repository.sum_by_period(
                db,
                tenant_id=tenant_id,
                since=month_start,
            )

            by_model = self.repository.group_by_model(
                db,
                tenant_id=tenant_id,
                since=month_start,
            )

            by_user = self.repository.group_by_user(
                db,
                tenant_id=tenant_id,
                since=month_start,
            )

        finally:

            db.close()

        return {
            "today": today,
            "month": month,
            "by_model": by_model,
            "by_user": by_user,
            "budget": self.get_budget(tenant_id),
        }


    def _month_spend(
            self,
            tenant_id: str
    ) -> float:

        now = datetime.now()

        month_start = datetime(
            now.year,
            now.month,
            1,
        )

        db = SessionLocal()

        try:

            return self.repository.sum_by_period(
                db,
                tenant_id=tenant_id,
                since=month_start,
            )["cost"]

        finally:

            db.close()


    def _get_config_service(self):

        if self.config_service is None:

            return agent_config_service

        return self.config_service


# 全局单例
cost_governance_service = CostGovernanceService()
