from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from work_agent.db.models import LLMCostRecord


class LLMCostRepository:

    """
    LLM 成本数据访问（租户隔离）
    """

    def create(
            self,
            db: Session,
            *,
            tenant_id: str,
            request_id: str,
            user_id: int | None,
            model: str,
            input_tokens: int,
            output_tokens: int,
            total_tokens: int,
            cost: float
    ) -> LLMCostRecord:

        row = LLMCostRecord(
            tenant_id=tenant_id,
            request_id=request_id,
            user_id=user_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cost=cost,
        )

        db.add(row)

        db.commit()

        return row


    def sum_by_period(
            self,
            db: Session,
            *,
            tenant_id: str,
            since: datetime
    ) -> dict:

        """
        统计某租户 since 之后的成本与 token
        """

        base = (
            db.query(LLMCostRecord)
            .filter(
                LLMCostRecord.tenant_id == tenant_id,
                LLMCostRecord.created_at >= since,
            )
        )

        row = (
            base
            .with_entities(
                func.coalesce(func.sum(LLMCostRecord.cost), 0.0),
                func.coalesce(func.sum(LLMCostRecord.total_tokens), 0),
                func.count(LLMCostRecord.id),
            )
            .first()
        )

        return {
            "cost": round(float(row[0] or 0.0), 4),
            "tokens": int(row[1] or 0),
            "requests": int(row[2] or 0),
        }


    def group_by_model(
            self,
            db: Session,
            *,
            tenant_id: str,
            since: datetime
    ) -> list[dict]:

        rows = (
            db.query(
                LLMCostRecord.model,
                func.coalesce(func.sum(LLMCostRecord.cost), 0.0),
                func.coalesce(func.sum(LLMCostRecord.total_tokens), 0),
            )
            .filter(
                LLMCostRecord.tenant_id == tenant_id,
                LLMCostRecord.created_at >= since,
            )
            .group_by(LLMCostRecord.model)
            .all()
        )

        return [
            {
                "model": model,
                "cost": round(float(cost), 4),
                "tokens": int(tokens),
            }
            for model, cost, tokens in rows
        ]


    def group_by_user(
            self,
            db: Session,
            *,
            tenant_id: str,
            since: datetime
    ) -> list[dict]:

        rows = (
            db.query(
                LLMCostRecord.user_id,
                func.coalesce(func.sum(LLMCostRecord.cost), 0.0),
                func.count(LLMCostRecord.id),
            )
            .filter(
                LLMCostRecord.tenant_id == tenant_id,
                LLMCostRecord.created_at >= since,
            )
            .group_by(LLMCostRecord.user_id)
            .all()
        )

        return [
            {
                "user_id": user_id,
                "cost": round(float(cost), 4),
                "requests": int(requests),
            }
            for user_id, cost, requests in rows
        ]
