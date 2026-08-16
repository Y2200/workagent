"""
企业任务决策层（Policy Decision Layer，Phase 7A）

意图/计划级前置 RBAC。确定性、无 LLM、纯函数。
插入 runtime 中 planner.plan 之后、supervisor.dispatch 之前。

职责：
- 根据 intent + plan.steps + context(permissions/role_codes/department/is_system)
  判定该计划是否允许执行
- 双保险：Policy 是第一道防线；Tool 层 check_permission 保留为第二道防线
- System Agent：is_system=True 跳过用户角色校验，但执行 System Permission Check

聚焦任务执行权限（task/notification/report）；
POLICY_QUERY（制度查询）不纳入全局权限中心，继续用 RAG 文档级 ACL。
"""

from dataclasses import dataclass, field

from work_agent.agent.schemas import IntentType
from work_agent.agent.tools.registry import tool_registry


# ======================
# 权限等价（兼容未重刷 RBAC 的旧库）
# ======================

EQUIVALENT_PERMISSIONS: dict[str, set[str]] = {
    # policy:view 等价 document:view（旧库 USER 只有 document:view）
    "policy:view": {"policy:view", "document:view"},
}


# ======================
# 管理角色（部门任务/员工任务/汇总需管理角色）
# ======================

MANAGEMENT_ROLES = {
    "SUPER_ADMIN",
    "TENANT_ADMIN",
    "DEPARTMENT_ADMIN",
}


# 需要管理角色的 (tool, action)
ROLE_REQUIRED_STEPS = {
    ("task_tool", "department_tasks"),
    ("task_tool", "employee_tasks"),
    ("task_tool", "summary"),
}


# ======================
# 意图级权限覆盖表
# 意图 → 工具 → action → 所需权限（OR 集合）
# 不在表中的 action 回退 tool_registry 声明的 REQUIRED_PERMISSION/PERMISSION_MAP
# ======================

# confirm/cancel 双用途：员工确认进度(submit) 或 经理确认创建(create)
DUAL_PERMISSION_CODES = ("task:submit", "task:create")

INTENT_ACTION_PERMISSIONS: dict[str, dict[str, dict[str, tuple]]] = {
    # 制度查询：RAG ACL 负责文档级，Policy 只透传（不拦 policy_query 权限）
    IntentType.POLICY_QUERY: {},

    # 员工查自己的任务
    IntentType.QUERY_MY_TASK: {
        "task_tool": {
            "list": ("task:view",),
            "detail": ("task:view",),
        },
    },

    # 经理查员工/部门任务（需管理角色 + task:view_employee）
    IntentType.QUERY_EMPLOYEE_TASK: {
        "task_tool": {
            "department_tasks": ("task:view_employee",),
            "employee_tasks": ("task:view_employee",),
        },
    },

    # 经理发布任务
    IntentType.CREATE_TASK: {
        "task_tool": {
            "create": ("task:create",),
            "confirm": DUAL_PERMISSION_CODES,
            "cancel": DUAL_PERMISSION_CODES,
        },
    },

    # 员工提交/确认/取消/完成进度
    IntentType.SUBMIT_TASK: {
        "task_tool": {
            "submit": ("task:submit",),
            "submit_all": ("task:submit",),
            "complete": ("task:submit",),
            "confirm": DUAL_PERMISSION_CODES,
            "cancel": DUAL_PERMISSION_CODES,
        },
    },

    # 经理提醒/督促员工
    IntentType.REMIND_TASK: {
        "notification_tool": {
            "send_wechat": ("task:remind",),
            "send_email": ("task:remind", "email:send"),  # 双权限 AND
        },
    },

    # 部门任务汇总（Manager 或 System）
    IntentType.SUMMARY_TASK: {
        "task_tool": {
            "summary": ("task:view_employee", "report:send"),
        },
    },

    # System 扫描（系统链路）
    "system_scan": {
        "reminder_service": {
            "scan": ("system:scan",),
        },
    },
}


# ======================
# 拒绝重定向建议
# ======================

REDIRECT_MAP: dict[tuple, str] = {
    ("task_tool", "create"): (
        "你没有发布任务权限。可以提交自己的任务结果，或查看自己的任务。"
    ),
    ("task_tool", "employee_tasks"): (
        "仅部门经理可查看员工任务；你可回复「我的任务」查看自己的任务。"
    ),
    ("task_tool", "department_tasks"): (
        "仅部门经理可查看部门任务；你可回复「我的任务」查看自己的任务。"
    ),
    ("task_tool", "summary"): (
        "仅部门经理可查看部门任务汇总。"
    ),
}


# ======================
# 结果结构
# ======================

@dataclass
class DeniedStep:
    step_id: int
    tool: str
    action: str
    required: str
    message: str


@dataclass
class PolicyDecision:
    allowed: bool
    denied: list[DeniedStep] = field(default_factory=list)
    message: str = ""
    redirect: str = ""


class PolicyService:

    """
    企业任务决策层
    """

    def evaluate(
            self,
            *,
            intent: str,
            plan,
            context
    ) -> PolicyDecision:

        """
        评估计划是否允许执行

        - is_system：跳过用户角色校验，但执行 System Permission Check
        - steps 为空（chat/legacy/UNKNOWN）：放行
        - 逐 step 校验权限 + 角色
        """

        # System Agent：执行 System Permission Check，不直接放行
        if getattr(context, "is_system", False):

            return self._evaluate_system(
                intent=intent,
                plan=plan,
                context=context,
            )

        # 无步骤（chat/legacy/unknown）：放行
        if not plan or not plan.steps:
            return PolicyDecision(allowed=True)

        denied: list[DeniedStep] = []

        for step in plan.steps:

            tool = step.tool or ""
            action = step.action or ""

            # 意图级权限覆盖表 → 回退 tool_registry 声明
            required_codes = self._required_codes(
                intent,
                tool,
                action,
            )

            if required_codes:

                missing = self._missing_permissions(
                    context,
                    required_codes,
                )

                if missing:

                    denied.append(
                        DeniedStep(
                            step_id=step.step_id,
                            tool=tool,
                            action=action,
                            required=",".join(required_codes),
                            message=f"无 {','.join(required_codes)} 权限",
                        )
                    )

            # 角色级校验（部门/员工任务/汇总需管理角色）
            if (tool, action) in ROLE_REQUIRED_STEPS:

                role_codes = getattr(
                    context,
                    "role_codes",
                    set(),
                )

                if not (role_codes & MANAGEMENT_ROLES):

                    denied.append(
                        DeniedStep(
                            step_id=step.step_id,
                            tool=tool,
                            action=action,
                            required="管理角色",
                            message="需要部门经理及以上角色",
                        )
                    )

        if denied:

            return PolicyDecision(
                allowed=False,
                denied=denied,
                message=self._build_message(denied),
                redirect=self._redirect(tool, action),
            )

        return PolicyDecision(allowed=True)


    def _evaluate_system(
            self,
            *,
            intent: str,
            plan,
            context
    ) -> PolicyDecision:

        """
        System Agent 校验：只允许 system:scan / task:remind / report:send
        禁止普通用户任务权限。
        """

        system_permissions = getattr(
            context,
            "permissions",
            set(),
        )

        # 系统允许的权限
        allowed_system = {
            "system:scan",
            "task:remind",
            "report:send",
        }

        if not (system_permissions & allowed_system):

            return PolicyDecision(
                allowed=False,
                message="System Agent 权限不足（需要 system:scan/task:remind/report:send）",
            )

        return PolicyDecision(allowed=True)


    def _required_codes(
            self,
            intent: str,
            tool: str,
            action: str
    ) -> tuple | None:

        """
        意图级覆盖表 → 回退 tool_registry 声明
        """

        intent_table = INTENT_ACTION_PERMISSIONS.get(intent, {})

        codes = intent_table.get(tool, {}).get(action)

        if codes:
            return codes

        # 回退 tool_registry 声明
        tool_obj = tool_registry.get(tool)

        if not tool_obj:
            return None

        if getattr(tool_obj, "REQUIRED_PERMISSION", ""):

            return (tool_obj.REQUIRED_PERMISSION,)

        return (
            (tool_obj.PERMISSION_MAP.get(action),)
            if action in getattr(tool_obj, "PERMISSION_MAP", {})
            else None
        )


    def _missing_permissions(
            self,
            context,
            required_codes: tuple
    ) -> list[str]:

        """
        检查缺失权限（OR 语义：有任一即通过；AND 需全部）

        required_codes 长度 > 1 且非 DUAL（AND 语义，如 send_email 需双权限）
        此处统一按 AND 处理（全需满足）；OR 场景（confirm/cancel 双用途）
        通过 required_codes 的等价展开 + 任一命中即通过。
        """

        permissions = getattr(
            context,
            "permissions",
            set(),
        )

        # 等价展开（policy:view 等价 document:view）
        expanded = set(permissions)

        for perm in permissions:

            expanded |= EQUIVALENT_PERMISSIONS.get(perm, set())

        # OR 语义（confirm/cancel 双用途）：任一命中即通过
        if required_codes == DUAL_PERMISSION_CODES:

            missing = [
                c for c in required_codes
                if c not in expanded
            ]

            # 任一命中即通过
            if len(missing) < len(required_codes):
                return []

            return missing

        # AND 语义：全部需满足
        return [
            c for c in required_codes
            if c not in expanded
        ]


    def _build_message(self, denied: list[DeniedStep]) -> str:

        first = denied[0]

        return first.message


    def _redirect(self, tool: str, action: str) -> str:

        return REDIRECT_MAP.get(
            (tool, action),
            "",
        )


# 全局单例
policy_service = PolicyService()
