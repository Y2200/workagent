"""
任务督导服务

职责：
- 创建/查询任务
- 接收员工进度反馈 → AI 解析 → 生成待确认
- 员工确认后落库（task_updates + tasks.progress）
- 任务完成/取消

隔离铁律：所有查询按 tenant_id 过滤；员工只能操作自己的任务
"""

import re
import time

from datetime import datetime

from work_agent.core.exceptions import TenantAccessDenied
from work_agent.db.session import SessionLocal
from work_agent.repositories.task_repository import TaskRepository
from work_agent.repositories.user_repository import UserRepository


_PROGRESS_RE = re.compile(
    r"(\d{1,3})\s*[%％]"
)


class TaskService:

    def __init__(
            self,
            repository: TaskRepository | None = None
    ):

        self.repository = repository or TaskRepository()

    # ======================
    # 任务查询 / 创建
    # ======================

    def create_task(
            self,
            *,
            creator_tenant_id: str,
            title: str,
            description: str = "",
            creator_id: int | None = None,
            manager_id: int | None = None,
            employee_id: int,
            department: str = "",
            deadline: datetime | None = None,
            priority: str = "normal"
    ):

        """
        创建任务

        多租户铁律：任务 tenant_id 归属「数据所有者」= 负责人 employee 的租户，
        （创建者可能是平台管理员，其 tenant_id 为空，不能作为任务租户）。
        前端禁止传 tenant_id；两者皆空则拒绝创建。
        """

        db = SessionLocal()

        try:

            employee = UserRepository().get_by_id(
                db,
                employee_id,
            )

            if not employee:

                raise ValueError(
                    f"负责人不存在: {employee_id}"
                )

            task_tenant = (
                employee.tenant_id
                or creator_tenant_id
            )

            if not task_tenant:

                raise ValueError(
                    "无法确定任务租户：负责人与创建者均无租户"
                )

            return self.repository.create(
                db,
                tenant_id=task_tenant,
                title=title,
                description=description,
                creator_id=creator_id,
                manager_id=manager_id,
                employee_id=employee_id,
                department=department,
                deadline=deadline,
                priority=priority,
            )

        finally:

            db.close()

    def get_task(
            self,
            *,
            tenant_id: str,
            task_id: int
    ):

        db = SessionLocal()

        try:

            task = self.repository.get_by_id(
                db,
                task_id,
            )

            if task and task.tenant_id != tenant_id:

                raise TenantAccessDenied(
                    "跨租户访问任务"
                )

            return task

        finally:

            db.close()

    def list_tasks_for_web(
            self,
            *,
            tenant_id: str,
            status: str | None = None
    ):

        db = SessionLocal()

        try:

            return self.repository.list_by_tenant(
                db,
                tenant_id,
                status=status,
            )

        finally:

            db.close()

    def list_employee_tasks(
            self,
            *,
            tenant_id: str,
            employee_id: int
    ):

        db = SessionLocal()

        try:

            return self.repository.get_employee_tasks(
                db,
                tenant_id,
                employee_id,
            )

        finally:

            db.close()

    def list_task_updates(
            self,
            *,
            tenant_id: str,
            task_id: int
    ):

        task = self.get_task(
            tenant_id=tenant_id,
            task_id=task_id,
        )

        if not task:

            return []

        db = SessionLocal()

        try:

            return self.repository.list_updates(
                db,
                task_id,
            )

        finally:

            db.close()

    # ======================
    # 进度反馈 → 待确认
    # ======================

    def submit_progress_feedback(
            self,
            *,
            tenant_id: str,
            employee_id: int,
            content: str,
            force_progress: int | None = None
    ) -> dict:

        """
        员工反馈进度：解析 → 生成待确认（不落正式表）

        返回：
        {
            "status": "awaiting_confirmation",
            "task": {...}, "parsed": {...}
        }
        或错误：
        {"status": "no_tasks" | "task_not_found", "message": "..."}
        """

        db = SessionLocal()

        try:

            tasks = self.repository.get_employee_tasks(
                db,
                tenant_id,
                employee_id,
            )

            if not tasks:

                return {
                    "status": "no_tasks",
                    "message": "你目前没有进行中的任务。",
                }

            parsed = self._parse_feedback(
                content,
                task_titles=[t.title for t in tasks],
            )

            if force_progress is not None:

                parsed["progress"] = max(
                    0,
                    min(100, int(force_progress)),
                )

            task = self._resolve_task(
                tasks,
                parsed.get("task_title", ""),
            )

            if not task:

                # 兜底：LLM 未解析出任务名时，直接从反馈内容匹配任务标题
                task = self._resolve_task_from_content(
                    tasks,
                    content,
                )

            if not task and len(tasks) == 1:

                # 员工只有一个任务时自动认定（如直接说"任务完成"）
                task = tasks[0]

            if not task:

                titles = "\n".join(
                    f"{i + 1}. {t.title}"
                    for i, t in enumerate(tasks)
                )

                return {
                    "status": "task_not_found",
                    "message": (
                        "没识别出你反馈的是哪个任务，请指明任务名。\n"
                        "你当前的任务：\n"
                        + titles
                    ),
                }

            pending = self.repository.upsert_pending(
                db,
                task_id=task.id,
                employee_id=employee_id,
                content=content,
                parsed=parsed,
            )

            return {
                "status": "awaiting_confirmation",
                "pending_id": pending.id,
                "task": self._task_dict(task),
                "parsed": parsed,
            }

        finally:

            db.close()

    def confirm_pending(
            self,
            *,
            tenant_id: str,
            employee_id: int
    ) -> dict:

        """
        员工确认：pending → task_updates + tasks.progress

        返回：
        {"status": "confirmed", "task": {...}, "parsed": {...}}
        或 {"status": "no_pending", "message": "..."}
        """

        db = SessionLocal()

        try:

            pending, task = self.repository.get_latest_pending(
                db,
                tenant_id,
                employee_id,
            )

            if not pending or not task:

                return {
                    "status": "no_pending",
                    "message": "当前没有待确认的提交。",
                }

            parsed = pending.parsed or {}

            progress = int(
                parsed.get("progress", task.progress)
            )

            summary = (
                parsed.get("summary", "")
                or pending.content
            )

            self.repository.add_update(
                db,
                task_id=task.id,
                employee_id=employee_id,
                content=pending.content,
                progress=progress,
                ai_summary=summary,
                confirmed=True,
            )

            self.repository.update_progress(
                db,
                task.id,
                progress,
            )

            self.repository.clear_pending(
                db,
                task.id,
                employee_id,
            )

            return {
                "status": "confirmed",
                "task": self._task_dict(task),
                "parsed": parsed,
            }

        finally:

            db.close()

    def cancel_pending(
            self,
            *,
            tenant_id: str,
            employee_id: int
    ) -> dict:

        db = SessionLocal()

        try:

            pending, task = self.repository.get_latest_pending(
                db,
                tenant_id,
                employee_id,
            )

            if not pending:

                return {
                    "status": "no_pending",
                    "message": "当前没有待确认的提交。",
                }

            self.repository.clear_pending(
                db,
                task.id,
                employee_id,
            )

            return {
                "status": "cancelled",
                "task": self._task_dict(task) if task else None,
            }

        finally:

            db.close()

    # ======================
    # 内部：AI 解析
    # ======================

    def _parse_feedback(
            self,
            content: str,
            task_titles: list[str]
    ) -> dict:

        """
        LLM 解析进度反馈；失败回退确定性提取
        """

        try:

            from work_agent.agent.llm import get_llm

            from work_agent.core.prompt_manager import prompt_manager

            from work_agent.core.utils import parse_json

            loaded = prompt_manager.load(
                "task_progress_parse"
            )

            result = get_llm().invoke(
                loaded["content"].format(
                    message=content,
                    task_list="\n".join(
                        f"- {title}"
                        for title in task_titles
                    ),
                )
            )

            data = parse_json(
                result.content
            )

            progress = int(
                data.get("progress", 0)
            )

            if not 0 <= progress <= 100:

                progress = self._extract_progress(content)

            return {
                "task_title": (
                    data.get("task_title", "")
                    or ""
                ),
                "progress": progress,
                "summary": (
                    data.get("summary", "")
                    or content[:100]
                ),
                "done": list(
                    data.get("done", [])
                    or []
                ),
                "remaining": list(
                    data.get("remaining", [])
                    or []
                ),
            }

        except Exception:

            return self._fallback_parse(
                content,
                task_titles,
            )

    def _fallback_parse(
            self,
            content: str,
            task_titles: list[str]
    ) -> dict:

        progress = self._extract_progress(content)

        task_title = next(
            (
                title
                for title in task_titles
                if title and title in content
            ),
            "",
        )

        return {
            "task_title": task_title,
            "progress": progress,
            "summary": content[:100],
            "done": [],
            "remaining": [],
        }

    @staticmethod
    def _extract_progress(
            content: str
    ) -> int:

        match = _PROGRESS_RE.search(
            content
        )

        if match:

            value = int(match.group(1))

            return max(0, min(100, value))

        # 中文数字启发式
        if "全部完成" in content or "已经完成" in content:

            return 100

        return 0

    @staticmethod
    def _resolve_task(
            tasks,
            task_title: str
    ):

        if not task_title:

            return None

        task_title = task_title.strip()

        for task in tasks:

            if task.title == task_title:

                return task

        # 子串匹配（模糊）
        for task in tasks:

            if task_title in task.title or task.title in task_title:

                return task

        return None

    @staticmethod
    def _resolve_task_from_content(
            tasks,
            content: str
    ):

        """
        确定性兜底：反馈内容里出现哪个任务标题就用哪个
        """

        for task in tasks:

            if task.title and task.title in content:

                return task

        return None

    @staticmethod
    def _task_dict(
            task
    ) -> dict:

        return {
            "id": task.id,
            "title": task.title,
            "status": task.status,
            "progress": task.progress,
            "priority": task.priority,
            "deadline": (
                task.deadline.isoformat()
                if task.deadline
                else None
            ),
            "department": task.department,
        }


# 全局单例
task_service = TaskService()
