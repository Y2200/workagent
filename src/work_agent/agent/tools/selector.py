import json

from work_agent.agent.context import AgentContext
from work_agent.agent.llm import get_llm
from work_agent.agent.schemas import IntentType
from work_agent.core.prompt_manager import prompt_manager
from work_agent.core.utils import parse_json
from work_agent.agent.tools.registry import tool_registry


class ToolSelector:

    """
    工具选择器

    输入：intent + entities + message
    输出：{tool, action, args}

    LLM 选择失败时回退确定性映射
    """

    # 确定性映射（回退）
    ACTION_TOOL_MAP = {
        "upload": ("document_tool", "upload"),
        "delete": ("document_tool", "delete"),
        "list": ("document_tool", "list"),
        "view_permission": ("permission_tool", "get"),
        "update_permission": ("permission_tool", "update"),
    }


    def __init__(
            self,
            llm=None
    ):

        self.llm = llm or get_llm()

        self.last_prompt_version = ""


    def select(
            self,
            *,
            intent: str,
            entities: dict,
            message: str,
            context: AgentContext
    ) -> dict:

        if intent == IntentType.KNOWLEDGE_QUERY:

            return {
                "tool": "knowledge_tool",
                "action": None,
                "args": {},
            }

        if intent == IntentType.DOCUMENT_OPERATION:

            # 先尝试 LLM 选择
            try:

                selection = self._llm_select(
                    intent,
                    entities,
                    message,
                )

                if selection.get("tool"):

                    return selection

            except Exception:
                pass

            # 回退确定性映射
            return self._fallback(entities)

        return {
            "tool": None,
            "action": None,
            "args": {},
        }


    def _llm_select(
            self,
            intent: str,
            entities: dict,
            message: str
    ) -> dict:

        loaded = prompt_manager.load(
            "tool_selector"
        )

        self.last_prompt_version = loaded["version"]

        prompt = loaded["content"].format(
            message=message,
            intent=intent,
            entities=json.dumps(
                entities,
                ensure_ascii=False,
            ),
            available_tools=json.dumps(
                tool_registry.list_tools(),
                ensure_ascii=False,
            ),
        )

        result = self.llm.invoke(
            prompt
        )

        data = parse_json(
            result.content
        )

        tool = data.get("tool", "")

        if not tool_registry.get(tool):
            return {}

        return {
            "tool": tool,
            "action": data.get("action", ""),
            "args": data.get("args", {}) or {},
        }


    def _fallback(
            self,
            entities: dict
    ) -> dict:

        action = entities.get(
            "action",
            "list"
        )

        tool, mapped_action = self.ACTION_TOOL_MAP.get(
            action,
            ("document_tool", "list"),
        )

        args = {}

        document_ref = entities.get(
            "document_ref"
        )

        if document_ref:

            try:
                args["document_id"] = int(document_ref)
            except (TypeError, ValueError):
                pass

        return {
            "tool": tool,
            "action": mapped_action,
            "args": args,
        }


# 全局单例
tool_selector = ToolSelector()
