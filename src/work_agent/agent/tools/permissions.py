"""
Enterprise Agent 权限共享工具

部门作用域校验：DEPARTMENT_ADMIN 仅允许操作本部门数据。

注：department 目前是自由文本字符串（user.department / tasks.department）。
TODO(Enterprise)：后续引入 departments 表 + department_id 外键后，
改为按 department_id 关联校验（见 plan Phase 2 设计约束）。
"""


def check_department_scope(
        context,
        target_department: str
) -> bool:

    """
    部门作用域校验

    规则：
    - 非 DEPARTMENT_ADMIN（SUPER_ADMIN/TENANT_ADMIN/USER）→ 放行
      （SUPER_ADMIN/TENANT_ADMIN 租户级全量；USER 无部门维度，由权限码限制）
    - DEPARTMENT_ADMIN → 仅允许操作本部门（context.department 字符串匹配）
    """

    role_codes = getattr(
        context,
        "role_codes",
        set(),
    )

    if "DEPARTMENT_ADMIN" not in role_codes:

        return True

    own_department = getattr(
        context,
        "department",
        "",
    ) or ""

    target = target_department or ""

    return own_department == target
