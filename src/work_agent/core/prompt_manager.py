"""
企业级 Prompt 管理

职责：
- 加载 Prompt（按名称读 txt）
- 版本管理（基于 prompts/metadata.py 注册表）
- 缓存（PROMPT_CACHE_ENABLED）
- 清单/清缓存

业务代码禁止直接 open("prompts/xxx.txt")，统一走 PromptManager。
"""

from pathlib import Path

from work_agent.config import settings
from work_agent.core.exceptions import (
    PromptNotFoundError,
    PromptVersionError,
)
from work_agent.prompts.metadata import PROMPT_METADATA


class PromptManager:

    def __init__(
            self,
            path: str | None = None,
            cache_enabled: bool | None = None,
            metadata: dict | None = None
    ):

        self.path = Path(
            path or settings.prompt_path
        )

        self.cache_enabled = (
            settings.prompt_cache_enabled
            if cache_enabled is None
            else cache_enabled
        )

        self.metadata = metadata or PROMPT_METADATA

        # 名称 → {name, version, content}
        self._cache: dict[str, dict] = {}

        # Prompt 治理 resolver（P5-5-3）
        # 若返回 active DB 版本则优先使用，否则回退文件
        self._governance_resolver = None


    def load(
            self,
            name: str
    ) -> dict:

        """
        加载 Prompt

        返回：
        {
            "name": str,
            "version": str,
            "content": str
        }
        """

        if self.cache_enabled and name in self._cache:

            return self._cache[name]

        governed = self._resolve_governed(name)

        if governed:

            result = {
                "name": name,
                "version": governed["version"],
                "content": governed["content"],
            }

            if self.cache_enabled:

                self._cache[name] = result

            return result

        content = self._read(name)

        version = self.get_version(name)

        result = {
            "name": name,
            "version": version,
            "content": content,
        }

        if self.cache_enabled:

            self._cache[name] = result

        return result


    def get_version(
            self,
            name: str
    ) -> str:

        """
        读取 Prompt 版本（未注册元数据 → PromptVersionError）
        """

        meta = self.metadata.get(name)

        if not meta:

            raise PromptVersionError(
                f"Prompt '{name}' 未注册版本元数据"
            )

        version = meta.get("version")

        if not version:

            raise PromptVersionError(
                f"Prompt '{name}' 版本为空"
            )

        return version


    def clear_cache(self) -> None:

        self._cache.clear()


    def list_prompts(self) -> list[str]:

        """
        已注册的 Prompt 清单
        """

        return list(self.metadata.keys())


    def set_governance_resolver(
            self,
            resolver=None
    ) -> None:

        """
        注册 Prompt 治理 resolver（P5-5-3）

        resolver(name) → {version, content} | None
        None 表示无治理版本，回退文件
        """

        self._governance_resolver = resolver


    def _resolve_governed(
            self,
            name: str
    ) -> dict | None:

        if self._governance_resolver is None:
            return None

        try:

            return self._governance_resolver(name)

        except Exception:

            # 治理解析失败回退文件
            return None


    def _read(
            self,
            name: str
    ) -> str:

        path = self.path / f"{name}.txt"

        if not path.exists():

            raise PromptNotFoundError(name)

        return path.read_text(
            encoding="utf-8"
        )


# 全局单例
prompt_manager = PromptManager()
