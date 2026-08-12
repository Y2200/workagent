"""
Agent 健康监控服务

- check_components：逐依赖探活（PG/Milvus/MinIO/Redis/配置中心/Prompt）
- readiness：关键依赖（PG/Milvus/MinIO）全部 ok 才算就绪
- Redis 为可选依赖，不可用仅警告不判死
"""

from sqlalchemy import text

from work_agent.config import settings
from work_agent.db.session import engine


# 就绪判定中的关键依赖
_CRITICAL = {"postgres", "milvus", "minio"}


class HealthService:

    """
    健康监控
    """

    def check_components(self) -> list[dict]:

        return [
            self._check_postgres(),
            self._check_milvus(),
            self._check_minio(),
            self._check_redis(),
            self._check_config_center(),
            self._check_prompt(),
        ]


    def readiness(self) -> dict:

        components = self.check_components()

        critical_ok = all(
            comp["status"] == "ok"
            for comp in components
            if comp["name"] in _CRITICAL
        )

        return {
            "ready": critical_ok,
            "critical": sorted(_CRITICAL),
            "components": components,
        }


    # ======================
    # 各依赖探活
    # ======================

    @staticmethod
    def _ok(name: str, detail: str = "") -> dict:

        return {
            "name": name,
            "status": "ok",
            "detail": detail,
        }


    @staticmethod
    def _error(name: str, message: str) -> dict:

        return {
            "name": name,
            "status": "error",
            "detail": str(message)[:200],
        }


    def _check_postgres(self) -> dict:

        try:

            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))

            return self._ok("postgres")

        except Exception as exc:

            return self._error("postgres", exc)


    def _check_milvus(self) -> dict:

        try:

            from work_agent.core.container import rag_service

            rag_service.store.client.list_collections()

            return self._ok("milvus")

        except Exception as exc:

            return self._error("milvus", exc)


    def _check_minio(self) -> dict:

        try:

            from work_agent.core.container import minio_storage

            minio_storage.client.bucket_exists(
                minio_storage.bucket
            )

            return self._ok("minio")

        except Exception as exc:

            return self._error("minio", exc)


    def _check_redis(self) -> dict:

        try:

            import redis as redis_module

            client = redis_module.from_url(
                settings.redis_url
            )

            client.ping()

            return self._ok("redis")

        except Exception as exc:

            # 可选依赖：不可用仅警告
            return {
                "name": "redis",
                "status": "warn",
                "detail": str(exc)[:200],
            }


    def _check_config_center(self) -> dict:

        try:

            from work_agent.core.container import agent_config_service

            agent_config_service.get(
                "agent.default_top_k",
            )

            return self._ok("config_center")

        except Exception as exc:

            return self._error("config_center", exc)


    def _check_prompt(self) -> dict:

        try:

            from work_agent.core.prompt_manager import prompt_manager

            prompt_manager.load("intent_router")

            return self._ok("prompt")

        except Exception as exc:

            return self._error("prompt", exc)


# 全局单例
health_service = HealthService()
