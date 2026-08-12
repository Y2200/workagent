"""
Prompt 治理服务

生命周期：draft → approved → active（唯一）→ deprecated
- 激活的 DB 版本优先于文件（PromptManager 经 resolver 解析）
- 变更记录操作审计（prompt.activate）
"""

from pathlib import Path

from work_agent.config import settings
from work_agent.core.prompt_manager import prompt_manager
from work_agent.db.session import SessionLocal
from work_agent.prompts.metadata import PROMPT_METADATA
from work_agent.repositories.prompt_version_repository import PromptVersionRepository
from work_agent.services.audit_service import AuditService


class PromptGovernanceService:

    """
    Prompt 版本生命周期治理
    """

    def __init__(
            self,
            repository: PromptVersionRepository | None = None,
            audit_service: AuditService | None = None
    ):

        self.repository = repository or PromptVersionRepository()

        self.audit_service = audit_service or AuditService()


    def seed_from_files(
            self,
            tenant_id: str = ""
    ) -> int:

        """
        将 prompts/*.txt 作为 v1.0 active 基线入库（幂等）

        已存在 active 版本的 Prompt 跳过
        """

        path = Path(settings.prompt_path)

        seeded = 0

        for txt in sorted(path.glob("*.txt")):

            name = txt.stem

            db = SessionLocal()

            try:

                if self.repository.get_active(
                        db,
                        tenant_id=tenant_id,
                        name=name,
                ):
                    continue

                meta = PROMPT_METADATA.get(name, {})

                self.repository.create(
                    db,
                    tenant_id=tenant_id,
                    name=name,
                    version=meta.get("version", "1.0"),
                    content=txt.read_text(encoding="utf-8"),
                    status="active",
                    variables=meta.get("variables"),
                    description=meta.get("description", ""),
                    updated_by="system",
                )

                seeded += 1

            finally:

                db.close()

        return seeded


    def create_draft(
            self,
            *,
            name: str,
            content: str,
            description: str = "",
            updated_by: str = "",
            tenant_id: str = ""
    ) -> dict:

        """
        创建草稿（版本自动递增）
        """

        db = SessionLocal()

        try:

            existing = self.repository.list_by_name(
                db,
                tenant_id=tenant_id,
                name=name,
            )

            version = _next_version(
                [row.version for row in existing]
            )

            row = self.repository.create(
                db,
                tenant_id=tenant_id,
                name=name,
                version=version,
                content=content,
                status="draft",
                variables=PROMPT_METADATA.get(
                    name,
                    {},
                ).get("variables"),
                description=description,
                updated_by=updated_by,
            )

            return {
                "id": row.id,
                "name": name,
                "version": row.version,
                "status": row.status,
            }

        finally:

            db.close()


    def approve(
            self,
            *,
            name: str,
            version: str,
            updated_by: str = "",
            tenant_id: str = ""
    ) -> dict | None:

        """
        审批草稿 → approved
        """

        db = SessionLocal()

        try:

            row = self.repository.get_by_name_version(
                db,
                tenant_id=tenant_id,
                name=name,
                version=version,
            )

            if not row:
                return None

            self.repository.set_status(
                db,
                row,
                "approved",
            )

            return {
                "id": row.id,
                "name": name,
                "version": row.version,
                "status": "approved",
            }

        finally:

            db.close()


    def activate(
            self,
            *,
            name: str,
            version: str,
            updated_by: str = "",
            tenant_id: str = "",
            audit_tenant_id: str | None = None,
            audit_user_id: int | None = None
    ) -> dict | None:

        """
        激活版本（唯一 active，其余 deprecated）

        激活后清空 PromptManager 缓存，使新版本立即生效
        """

        db = SessionLocal()

        try:

            row = self.repository.get_by_name_version(
                db,
                tenant_id=tenant_id,
                name=name,
                version=version,
            )

            if not row:
                return None

            if row.status not in ("draft", "approved", "deprecated"):

                return None

            self.repository.deactivate_others(
                db,
                tenant_id=tenant_id,
                name=name,
                except_version=version,
            )

            row.status = "active"

            row.activated_at = _now()

            db.add(row)

            db.commit()

        finally:

            db.close()

        prompt_manager.clear_cache()

        self.audit_service.log_operation(
            tenant_id=audit_tenant_id or tenant_id,
            user_id=audit_user_id,
            action="prompt.activate",
            target_type="prompt",
            target_id=f"{name}@{version}",
        )

        return {
            "name": name,
            "version": version,
            "status": "active",
        }


    def deprecate(
            self,
            *,
            name: str,
            version: str,
            updated_by: str = "",
            tenant_id: str = ""
    ) -> dict | None:

        """
        弃用版本
        """

        db = SessionLocal()

        try:

            row = self.repository.get_by_name_version(
                db,
                tenant_id=tenant_id,
                name=name,
                version=version,
            )

            if not row:
                return None

            if row.status != "active":
                return None

            self.repository.set_status(
                db,
                row,
                "deprecated",
            )

            return {
                "name": name,
                "version": version,
                "status": "deprecated",
            }

        finally:

            db.close()


    def get_active(
            self,
            name: str,
            tenant_id: str = ""
    ):

        db = SessionLocal()

        try:

            return self.repository.get_active(
                db,
                tenant_id=tenant_id,
                name=name,
            )

        finally:

            db.close()


    def resolve_for_prompt(
            self,
            name: str
    ) -> dict | None:

        """
        PromptManager resolver：返回平台级 active 版本

        {name, version, content} 或 None（无治理版本 → 回退文件）
        """

        active = self.get_active(
            name,
            tenant_id="",
        )

        if not active:
            return None

        return {
            "version": active.version,
            "content": active.content,
        }


    def register_resolver(self) -> None:

        """
        注册治理 resolver 到 PromptManager
        """

        prompt_manager.set_governance_resolver(
            self.resolve_for_prompt
        )


    def list_history(
            self,
            name: str,
            tenant_id: str = ""
    ) -> list[dict]:

        db = SessionLocal()

        try:

            rows = self.repository.list_by_name(
                db,
                tenant_id=tenant_id,
                name=name,
            )

            return [
                {
                    "id": row.id,
                    "name": row.name,
                    "version": row.version,
                    "status": row.status,
                    "description": row.description,
                    "updated_by": row.updated_by,
                    "activated_at": row.activated_at,
                    "created_at": row.created_at,
                    "content": row.content,
                }
                for row in rows
            ]

        finally:

            db.close()


    def list_prompts(
            self,
            tenant_id: str = ""
    ) -> list[dict]:

        db = SessionLocal()

        try:

            names = self.repository.list_names(
                db,
                tenant_id=tenant_id,
            )

            prompts = []

            for name in names:

                active = self.repository.get_active(
                    db,
                    tenant_id=tenant_id,
                    name=name,
                )

                prompts.append(
                    {
                        "name": name,
                        "active_version": (
                            active.version
                            if active
                            else None
                        ),
                        "content": (
                            active.content
                            if active
                            else None
                        ),
                    }
                )

            return prompts

        finally:

            db.close()


def _next_version(existing: list[str]) -> str:

    """
    语义化版本自增：从已有版本取最大 major.minor，minor+1
    """

    max_major = 0

    max_minor = -1

    for version in existing:

        parts = str(version).split(".")

        try:

            major = int(parts[0])

            minor = int(parts[1]) if len(parts) > 1 else 0

        except (TypeError, ValueError):
            continue

        if major > max_major or (
                major == max_major and minor > max_minor
        ):

            max_major = major

            max_minor = minor

    if max_minor < 0:
        return "1.0"

    return f"{max_major}.{max_minor + 1}"


def _now():

    from datetime import datetime

    return datetime.now()


# 全局单例
prompt_governance_service = PromptGovernanceService()
