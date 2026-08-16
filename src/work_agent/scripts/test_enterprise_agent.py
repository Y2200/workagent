"""
Enterprise Agent 测试（Phase 1：Agent 基础能力）

Part A  BaseTool 权限钩子（REQUIRED_PERMISSION / PERMISSION_MAP / check_permission / denied）
Part A2 AgentContext.role_codes 注入
Part A3 ToolRegistry.list_tools 含权限信息
Part A4 TaskTool.input_schema action enum 完整（detail/submit_all）

用法：
    python -m work_agent.scripts.test_enterprise_agent
"""

from types import SimpleNamespace

# 副作用：触发 config.py 全局 stdout/stderr UTF-8 重配置（Windows GBK 兼容）
import work_agent.config  # noqa: F401

from work_agent.agent.context import AgentContext
from work_agent.agent.tools.base import BaseTool
from work_agent.agent.tools.registry import tool_registry
from work_agent.agent.tools.task_tool import TaskTool


def _ctx(
        permissions: set[str] | None = None,
        role_codes: set[str] | None = None,
        tenant_id: str = "1",
        department: str = "研发部",
):
    return AgentContext(
        request_id="test-1",
        tenant_id=tenant_id,
        user_id=1,
        username="tester",
        department=department,
        role="员工",
        permissions=set(permissions or []),
        role_codes=set(role_codes or []),
    )


def test_a_base_tool_permission_hook():
    """Part A1：BaseTool 权限钩子"""

    class FakeRequiredTool(BaseTool):
        REQUIRED_PERMISSION = "task:notify"

        def execute(self, **kwargs):
            return {}

    class FakeMappedTool(BaseTool):
        PERMISSION_MAP = {"delete": "document:delete", "view": "document:view"}

        def execute(self, **kwargs):
            return {}

    # REQUIRED_PERMISSION 缺失 → denied
    ctx_no_perm = _ctx(permissions={"task:view"})
    t = FakeRequiredTool()
    assert t.check_permission(ctx_no_perm) == "task:notify"
    denied = t.denied("task:notify")
    assert denied["error"] == "permission_denied"
    assert "task:notify" in denied["message"]

    # 有权限 → 通过
    ctx_ok = _ctx(permissions={"task:notify"})
    assert t.check_permission(ctx_ok) is None

    # PERMISSION_MAP action 维度
    m = FakeMappedTool()
    assert m.check_permission(_ctx({"document:view"}), "delete") == "document:delete"
    assert m.check_permission(_ctx({"document:view"}), "view") is None
    assert m.check_permission(_ctx({"document:view"}), "unknown") is None

    print("✓ PartA1 BaseTool 权限钩子")


def test_a2_context_role_codes():
    """Part A2：AgentContext.role_codes 注入与缺省"""
    ctx = _ctx(
        permissions={"task:view"},
        role_codes={"DEPARTMENT_ADMIN"},
    )
    assert ctx.role_codes == {"DEPARTMENT_ADMIN"}
    assert ctx.permissions == {"task:view"}

    # 缺省为空集（不传 role_codes 向后兼容）
    ctx_default = _ctx()
    assert ctx_default.role_codes == set()

    # build() 注入 role_codes
    user = SimpleNamespace(
        tenant_id="1", id=9, username="u", department="研发部", role="员工",
    )
    built = AgentContext.build(
        user=user,
        permissions={"task:view"},
        role_codes={"USER"},
    )
    assert built.role_codes == {"USER"}
    print("✓ PartA2 AgentContext.role_codes")


def test_a3_registry_permission_info():
    """Part A3：ToolRegistry.list_tools 含权限信息"""
    tools = {t["name"]: t for t in tool_registry.list_tools()}
    assert "task_tool" in tools

    task_info = tools["task_tool"]
    assert "required_permission" in task_info
    assert "permission_map" in task_info
    # task_tool 用 PERMISSION_MAP
    assert task_info["permission_map"].get("list") == "task:view"

    # 每个工具都有 name/description/input_schema（不破坏原有契约）
    for t in tool_registry.list_tools():
        assert t["name"]
        assert "description" in t
        assert "input_schema" in t
    print("✓ PartA3 ToolRegistry 权限信息")


def test_a4_task_tool_schema():
    """Part A4：TaskTool.input_schema action enum 完整"""
    schema = TaskTool().input_schema
    actions = schema["properties"]["action"]["enum"]
    for expected in ["list", "detail", "submit", "submit_all", "confirm", "cancel", "complete"]:
        assert expected in actions, f"input_schema 缺少 action: {expected}"
    # PERMISSION_MAP 与 schema 对齐
    assert set(TaskTool.PERMISSION_MAP.keys()) == set(actions)
    print("✓ PartA4 TaskTool input_schema")


def test():
    print("== Enterprise Agent 测试（Phase 1）==")
    test_a_base_tool_permission_hook()
    test_a2_context_role_codes()
    test_a3_registry_permission_info()
    test_a4_task_tool_schema()
    print("Enterprise Agent 测试全部通过")


if __name__ == "__main__":
    test()
