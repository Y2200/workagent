"""
审计日志生命周期管理

用法：
    python -m work_agent.scripts.archive_audit_logs            # 标记过期日志为已归档
    python -m work_agent.scripts.archive_audit_logs --purge    # 额外硬删除已归档超30天的日志

只标记归档，不破坏审计追踪。
"""

import argparse

from datetime import datetime, timedelta

from sqlalchemy import text

from work_agent.config import settings
from work_agent.db.models import AgentLog
from work_agent.db.session import SessionLocal, engine
from work_agent.repositories.agent_log_repository import AgentLogRepository
from work_agent.repositories.tenant_repository import TenantRepository


def _all_tenant_ids() -> list[str]:

    db = SessionLocal()

    try:

        tenant_ids = [
            str(tenant.id)
            for tenant in TenantRepository().list(db)
        ]

        # 默认租户（单租户占位）
        tenant_ids.append("")

        return tenant_ids

    finally:

        db.close()


def archive() -> int:

    retention = settings.audit_log_retention_days

    cutoff = datetime.now() - timedelta(
        days=retention
    )

    repository = AgentLogRepository()

    db = SessionLocal()

    try:

        total = 0

        for tenant_id in _all_tenant_ids():

            archived = repository.archive_expired(
                db,
                tenant_id,
                cutoff,
            )

            total += archived

        print(
            f"归档完成: {total} 条过期日志(>{retention}天)标记为已归档"
        )

        return total

    finally:

        db.close()


def purge() -> int:

    """
    硬删除已归档且超过 30 天的日志（彻底清理）
    """

    cutoff = datetime.now() - timedelta(
        days=30
    )

    with engine.begin() as conn:

        result = conn.execute(
            text(
                "DELETE FROM agent_logs "
                "WHERE archived_at IS NOT NULL "
                "AND archived_at < :cutoff"
            ),
            {"cutoff": cutoff},
        )

    print(
        f"清理完成: {result.rowcount} 条已归档日志被硬删除"
    )

    return result.rowcount


def main():

    parser = argparse.ArgumentParser(
        description="审计日志生命周期管理"
    )

    parser.add_argument(
        "--purge",
        action="store_true",
        help="同时硬删除已归档超30天的日志",
    )

    args = parser.parse_args()

    archived = archive()

    if args.purge:

        deleted = purge()

        print(
            f"共标记 {archived} 条，硬删除 {deleted} 条"
        )


if __name__ == "__main__":

    main()
