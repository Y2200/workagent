from work_agent.core.config_defs import CONFIG_DEFINITIONS
from work_agent.db.session import SessionLocal
from work_agent.repositories.agent_config_repository import AgentConfigRepository


class AgentConfigService:

    """
    Agent 配置中心

    取值优先级：租户覆盖 → 平台默认 → 内置默认
    提供内存缓存，set 时失效（单进程足够；分布式后续接 Redis）
    """

    def __init__(
            self,
            repository: AgentConfigRepository | None = None
    ):

        self.repository = repository or AgentConfigRepository()

        # (tenant_id, config_key) → value
        self._cache: dict[tuple, object] = {}


    def get(
            self,
            key: str,
            tenant_id: str = ""
    ):

        """
        返回生效配置值（None = 未设置）
        """

        cache_key = (tenant_id, key)

        if cache_key in self._cache:
            return self._cache[cache_key]

        value = self._resolve(
            key,
            tenant_id,
        )

        self._cache[cache_key] = value

        return value


    def set(
            self,
            *,
            key: str,
            value,
            tenant_id: str = "",
            updated_by: str = "",
            description: str = ""
    ) -> None:

        """
        设置配置（租户级或平台级），并失效缓存
        """

        db = SessionLocal()

        try:

            self.repository.upsert(
                db,
                tenant_id=tenant_id,
                config_key=key,
                config_value=value,
                description=description,
                updated_by=updated_by,
            )

        finally:

            db.close()

        self._invalidate(key, tenant_id)


    def list_configs(
            self,
            tenant_id: str = ""
    ) -> list[dict]:

        """
        返回某租户的生效配置清单（内置默认 + 平台 + 租户覆盖）
        """

        db = SessionLocal()

        try:

            tenant_rows = {
                row.config_key: row
                for row in self.repository.list_by_tenant(
                    db,
                    tenant_id,
                )
            }

            platform_rows = {
                row.config_key: row
                for row in self.repository.list_platform(db)
            }

        finally:

            db.close()

        merged = []

        for key, definition in CONFIG_DEFINITIONS.items():

            if key in tenant_rows:

                row = tenant_rows[key]

                merged.append(
                    {
                        "key": key,
                        "value": row.config_value,
                        "scope": "tenant",
                        "description": row.description
                        or definition["description"],
                        "updated_by": row.updated_by,
                        "updated_at": row.updated_at,
                    }
                )

            elif key in platform_rows:

                row = platform_rows[key]

                merged.append(
                    {
                        "key": key,
                        "value": row.config_value,
                        "scope": "platform",
                        "description": row.description
                        or definition["description"],
                        "updated_by": row.updated_by,
                        "updated_at": row.updated_at,
                    }
                )

            else:

                merged.append(
                    {
                        "key": key,
                        "value": definition["default"],
                        "scope": "default",
                        "description": definition["description"],
                        "updated_by": "",
                        "updated_at": None,
                    }
                )

        return merged


    def is_tool_enabled(
            self,
            tool_name: str,
            tenant_id: str = ""
    ) -> bool:

        """
        工具是否启用（agent.tools.enabled 未设置 = 全部启用）
        """

        enabled = self.get(
            "agent.tools.enabled",
            tenant_id,
        )

        if enabled is None:
            return True

        if not isinstance(enabled, list):
            return True

        return tool_name in enabled


    def list_keys(self) -> list[str]:

        return list(CONFIG_DEFINITIONS.keys())


    def _effective_scope(
            self,
            key: str,
            tenant_id: str = ""
    ) -> str:

        """
        配置项当前生效层级：tenant / platform / default
        """

        db = SessionLocal()

        try:

            if tenant_id:

                row = self.repository.get(
                    db,
                    tenant_id=tenant_id,
                    config_key=key,
                )

                if row:
                    return "tenant"

            platform = self.repository.get(
                db,
                tenant_id="",
                config_key=key,
            )

            if platform:
                return "platform"

        finally:

            db.close()

        return "default"


    # ======================
    # 内部
    # ======================

    def _resolve(self, key: str, tenant_id: str):

        db = SessionLocal()

        try:

            if tenant_id:

                row = self.repository.get(
                    db,
                    tenant_id=tenant_id,
                    config_key=key,
                )

                if row:
                    return row.config_value

            platform = self.repository.get(
                db,
                tenant_id="",
                config_key=key,
            )

            if platform:
                return platform.config_value

        finally:

            db.close()

        return CONFIG_DEFINITIONS.get(
            key,
            {},
        ).get("default")


    def _invalidate(
            self,
            key: str,
            tenant_id: str
    ) -> None:

        self._cache.pop(
            (tenant_id, key),
            None,
        )

        # 平台级变更同时失效所有租户缓存
        if tenant_id == "":
            for cache_key in list(self._cache):
                if cache_key[1] == key:
                    self._cache.pop(cache_key, None)


# 全局单例
agent_config_service = AgentConfigService()
