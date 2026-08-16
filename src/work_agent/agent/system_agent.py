"""
System Proactive Agent（Phase 11）

系统定时动作经 Agent 判断后执行：
    Scheduler → System Agent → Policy(system=true) → Service

- is_system=True：跳过用户角色校验，但执行 System Permission Check
  （system:scan / task:remind / report:send）
- 扫描风险任务 → Agent 判断动作（提醒员工/通知经理/记录 audit）
- 非用户聊天触发，独立于 User 链路

设计：构造系统 AgentContext，走 Policy 校验（system 权限），
再调 task_reminder_service / notification_service。
"""

from uuid import uuid4

from work_agent.agent.context import AgentContext


# System Agent 允许的权限码（与 Policy 的 System Permission Check 对齐）
SYSTEM_PERMISSIONS = {
    "system:scan",
    "task:remind",
    "report:send",
}


def build_system_context(
        *,
        tenant_id: str = "",
        department: str = ""
) -> AgentContext:

    """
    构造系统 Agent 上下文（is_system=True + system 权限）
    """

    return AgentContext(
        request_id=str(uuid4()),
        tenant_id=tenant_id,
        user_id=None,
        username="system",
        department=department,
        role="system",
        permissions=set(SYSTEM_PERMISSIONS),
        role_codes=set(),
        is_system=True,
        channel="system",
    )


class SystemProactiveAgent:

    """
    系统主动 Agent：扫描风险 → 判断 → 提醒/通知/审计
    """

    name = "system_agent"


    def run_daily_scan(
            self,
            *,
            tenant_id: str = "",
            department: str = "",
            min_risk: str = "medium"
    ) -> dict:

        """
        每日主动扫描：

        1. 构造系统上下文 + Policy(system=true) 校验 system:scan
        2. scan_and_remind（确定性风险规则）
        3. 返回摘要（Agent 判断的动作已由 scan_and_remind 决定）
        """

        # 1. Policy System Permission Check
        from work_agent.agent.policy import policy_service
        from work_agent.agent.schemas import PlanResult, PlanStep

        ctx = build_system_context(
            tenant_id=tenant_id,
            department=department,
        )

        plan = PlanResult(
            kind="task",
            intent="system_scan",
            steps=[
                PlanStep(
                    step_id=1,
                    tool="reminder_service",
                    action="scan",
                ),
            ],
        )

        decision = policy_service.evaluate(
            intent="system_scan",
            plan=plan,
            context=ctx,
        )

        if not decision.allowed:

            return {
                "status": "denied",
                "message": decision.message,
            }

        # 2. 执行扫描（确定性风险判断）
        from work_agent.services.task_reminder_service import (
            task_reminder_service,
        )

        summary = task_reminder_service.scan_and_remind(
            min_risk=min_risk,
            department=department,
        )

        return {
            "status": "done",
            "agent": self.name,
            "is_system": True,
            "summary": summary,
        }


    def run_weekly_report(
            self,
            *,
            tenant_id: str = "",
            department: str = ""
    ) -> dict:

        """
        每周部门任务总结 → 发送部门经理（report:send）

        Policy 校验 report:send + task_remind。
        """

        # 1. Policy System Permission Check
        from work_agent.agent.policy import policy_service
        from work_agent.agent.schemas import PlanResult, PlanStep

        ctx = build_system_context(
            tenant_id=tenant_id,
            department=department,
        )

        plan = PlanResult(
            kind="task",
            intent="system_scan",
            steps=[
                PlanStep(
                    step_id=1,
                    tool="report_service",
                    action="weekly",
                ),
            ],
        )

        decision = policy_service.evaluate(
            intent="system_scan",
            plan=plan,
            context=ctx,
        )

        if not decision.allowed:

            return {
                "status": "denied",
                "message": decision.message,
            }

        # 2. 执行周报部门投递（report:send）
        from work_agent.services.task_report_service import (
            task_report_service,
        )

        result = task_report_service.send_department_digests(
            tenant_id=tenant_id or None,
        )

        return {
            "status": "done",
            "agent": self.name,
            "is_system": True,
            "summary": result,
        }


# 全局单例
system_proactive_agent = SystemProactiveAgent()
