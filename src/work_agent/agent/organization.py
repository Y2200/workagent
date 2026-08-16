"""
企业组织上下文（Enterprise Knowledge Agent，Phase 10）

Knowledge Agent 不只查制度文档，还结合用户身份 + 组织关系回答。
例如："我能不能申请远程办公？"
→ 制度规则（RAG）+ 用户角色/部门/权限（组织数据）

不保存企业事实到 Memory（企业事实由 RAG/DB 负责，会变化）；
本模块只是查询时实时组装用户画像，不做持久化。
"""

# 权限类问题关键词：触发组织维度追加
PERMISSION_QUERY_KEYWORDS = (
    "能不能",
    "是否可以",
    "有没有权限",
    "权限",
    "可以申请",
    "能申请",
    "是否有权",
    "能否",
    "能不能申请",
    "可以吗",
    "行不行",
    "允许吗",
    "允许我",
    "是否允许",
    "批准",
    "能否申请",
    "我可以申请",
    "我能申请",
)


def is_permission_query(message: str) -> bool:
    """
    判断是否为"权限/资格"类问题（需结合用户身份回答）
    """
    if not message:
        return False

    return any(
        kw in message
        for kw in PERMISSION_QUERY_KEYWORDS
    )


def build_user_profile(context) -> str:
    """
    构建用户画像（纯文本，供 LLM 结合制度回答权限类问题）

    只读 context 已注入的组织数据，不查 DB、不持久化。
    """

    username = getattr(context, "username", "") or ""

    department = getattr(context, "department", "") or ""

    role = getattr(context, "role", "") or ""

    role_codes = getattr(context, "role_codes", set()) or set()

    permissions = getattr(context, "permissions", set()) or set()

    # 角色码名称化
    role_names = {
        "SUPER_ADMIN": "超级管理员",
        "TENANT_ADMIN": "租户管理员",
        "DEPARTMENT_ADMIN": "部门经理",
        "USER": "普通员工",
    }

    role_labels = [
        role_names.get(code, code)
        for code in sorted(role_codes)
    ]

    lines = [
        f"姓名：{username}",
        f"部门：{department or '未分配'}",
    ]

    if role_labels:
        lines.append(f"角色：{'、'.join(role_labels)}")

    if permissions:
        perm_names = {
            "task:create": "发布任务",
            "task:submit": "提交任务",
            "task:view_employee": "查看员工任务",
            "task:remind": "提醒员工",
            "email:send": "发送邮件",
            "policy:view": "查看制度",
            "document:view": "查看文档",
            "document:create": "创建文档",
            "document:delete": "删除文档",
            "audit:view": "查看审计",
            "task:manage": "任务管理",
            "system:manage": "系统管理",
        }
        visible_perms = [
            perm_names.get(p, p)
            for p in sorted(permissions)
            if p in perm_names
        ]
        if visible_perms:
            lines.append(f"权限：{'、'.join(visible_perms)}")

    return "\n".join(lines)
