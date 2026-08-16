"""
Task Command Validator（企业任务命令校验，Phase 8）

把 LLM 输出的任务命令转成结构化 + 业务校验：
```
LLM Planner → Schema Validator → Policy Permission → Business Rule Validator
  → Service → DB
```

- Schema Validator：校验命令结构（assignee_id 为 int、title 非空、deadline 合法格式）
- Business Rule Validator：执行人存在 / 同部门 / deadline 合法 / 任务不重复
- 拒绝自由文本（如 {"text":"安排张三审核合同"}）

与 policy.py 的关系：
- policy.py 负责 RBAC 前置（第一道防线）
- validator.py 负责命令结构与业务规则（Phase 8）
- Tool 层 check_permission 保留（第二道防线）
"""

from dataclasses import dataclass


@dataclass
class ValidationResult:
    valid: bool
    errors: list[str] = None
    command: dict = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


class TaskCommandValidator:

    """
    任务命令校验器
    """

    def validate_command(
            self,
            command: dict | None
    ) -> ValidationResult:

        """
        Schema Validator：校验命令结构

        命令期望形如：
        {
            "intent": "create_task",
            "command": {
                "type": "task.create",
                "assignee_name": "张三",
                "title": "客户合同审核",
                "deadline": "2026-08-20"
            }
        }
        或已解析的：
        {
            "action": "create_task",
            "assignee_id": 123,
            "title": "...",
            "deadline": "2026-08-20",
            "creator_id": 45
        }
        """

        if not command:
            return ValidationResult(
                valid=False,
                errors=["缺少任务命令"],
            )

        # 嵌套结构：{"intent": "...", "command": {...}}
        inner = command

        if isinstance(command.get("command"), dict):

            inner = command["command"]

        errors = []

        # type / action 必须存在且为 create 类
        action = inner.get("type") or inner.get("action") or ""

        if not action:
            errors.append("缺少任务命令类型（type/action）")

        if action not in ("task.create", "create_task", "create"):

            errors.append(f"不支持的任务命令类型: {action}")

        # title 必须非空
        title = (inner.get("title") or "").strip()

        if not title:
            errors.append("任务名称（title）不能为空")

        # assignee：优先 id，其次 name
        assignee_id = inner.get("assignee_id")

        assignee_name = (inner.get("assignee_name") or "").strip()

        if not assignee_id and not assignee_name:

            errors.append("执行人（assignee）不能为空")

        # deadline：可选，但若有必须是合法格式（代码规则或 ISO）
        deadline = inner.get("deadline")

        if deadline:

            parsed = self._parse_deadline(deadline)

            if parsed is None:
                errors.append(f"截止时间（deadline）格式不合法: {deadline}")

        # 拒绝自由文本：无结构字段（如 {"text":"安排张三"}）
        if not inner.get("title") and not inner.get("action"):

            if any(k in inner for k in ("text", "content", "message")):

                errors.append(
                    "命令必须是结构化参数，不接受自由文本（如 text/content）"
                )

        if errors:

            return ValidationResult(
                valid=False,
                errors=errors,
            )

        return ValidationResult(
            valid=True,
            command={
                "action": "create_task",
                "assignee_id": (
                    int(assignee_id)
                    if assignee_id
                    else None
                ),
                "assignee_name": assignee_name or None,
                "title": title,
                "deadline": self._parse_deadline(deadline) if deadline else None,
            },
        )


    def validate_business(
            self,
            *,
            context,
            assignee_id: int | None,
            assignee_name: str | None,
            title: str,
            tenant_id: str = "",
            deadline=None
    ) -> ValidationResult:

        """
        Business Rule Validator：业务规则校验

        1. 执行人存在（DB 确定性）
        2. 执行人属于当前部门（check_department_scope）
        3. deadline 合法（若提供）
        4. 任务不重复（title + assignee 查重）
        """

        from work_agent.core.container import user_service

        errors = []

        # 1. 解析执行人（DB 确定性）
        target = None

        if assignee_id:

            target = user_service.get_by_id(assignee_id)

        elif assignee_name:

            users = user_service.search_by_name(
                keyword=assignee_name,
                tenant_id=(
                    tenant_id
                    if tenant_id
                    else ""
                ),
            )

            if len(users) == 1:

                target = users[0]

            elif len(users) > 1:

                errors.append(
                    f"「{assignee_name}」匹配到多个员工，请提供更完整姓名"
                )

        if not target and not errors:

            errors.append(
                f"执行人不存在: {assignee_name or assignee_id}"
            )

        if target and errors:
            return ValidationResult(valid=False, errors=errors)

        # 2. 部门作用域（DEPARTMENT_ADMIN 仅本部门）
        if target:

            from work_agent.agent.tools.permissions import check_department_scope

            if not check_department_scope(
                    context,
                    target.department or "",
            ):

                errors.append(
                    f"执行人「{target.real_name or target.username}」"
                    "不在当前部门，无法安排任务"
                )

        # 3. deadline 合法（validate_command 已查，此处再确认）
        # 4. 任务重复（title + assignee 查重）
        if target and not errors:

            duplicate = self._find_duplicate(
                tenant_id=tenant_id,
                assignee_id=target.id,
                title=title,
            )

            if duplicate:

                errors.append(
                    f"任务已存在：{title}"
                    f"（执行人 {target.real_name or target.username}）"
                )

        if errors:

            return ValidationResult(
                valid=False,
                errors=errors,
            )

        return ValidationResult(
            valid=True,
            command={
                "action": "create_task",
                "assignee_id": target.id if target else None,
                "assignee_name": (
                    target.real_name or target.username
                ) if target else assignee_name,
                "title": title,
                "deadline": deadline,
            },
        )


    @staticmethod
    def _find_duplicate(
            *,
            tenant_id: str,
            assignee_id: int,
            title: str
    ):

        """
        任务重复查重：同租户 + 同执行人 + 同任务名（未完成）

        经 task_service（分层铁律：Tool 禁直连 DB）
        """

        from work_agent.core.container import task_service

        try:

            tasks = task_service.list_employee_tasks(
                tenant_id=tenant_id,
                employee_id=assignee_id,
            )

            for t in tasks:

                if (
                    t.title.strip() == title.strip()
                    and t.status in ("pending", "processing")
                ):

                    return t

        except Exception:
            pass

        return None


    @staticmethod
    def _parse_deadline(deadline):

        """
        解析截止时间（代码规则 + ISO），无法解析返回 None
        """

        from work_agent.core.container import task_service

        return task_service._parse_deadline_text(str(deadline))


# 全局单例
task_command_validator = TaskCommandValidator()
