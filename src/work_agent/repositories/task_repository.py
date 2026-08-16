from datetime import datetime

from sqlalchemy.orm import Session

from work_agent.db.models.task import (
    Task,
    TaskPendingUpdate,
    TaskUpdate,
)


class TaskRepository:

    """
    任务数据访问
    """

    # ======================
    # 任务
    # ======================

    def create(
            self,
            db: Session,
            *,
            tenant_id: str,
            title: str,
            description: str = "",
            creator_id: int | None = None,
            manager_id: int | None = None,
            employee_id: int,
            department: str = "",
            deadline: datetime | None = None,
            priority: str = "normal"
    ) -> Task:

        task = Task(
            tenant_id=tenant_id,
            title=title,
            description=description,
            creator_id=creator_id,
            manager_id=manager_id,
            employee_id=employee_id,
            department=department,
            deadline=deadline,
            priority=priority,
            status="pending",
            progress=0,
        )

        db.add(task)

        db.commit()

        db.refresh(task)

        return task

    def get_by_id(
            self,
            db: Session,
            task_id: int
    ) -> Task | None:

        return db.get(
            Task,
            task_id,
        )

    def list_by_tenant(
            self,
            db: Session,
            tenant_id: str | None = None,
            status: str | None = None
    ) -> list[Task]:

        """
        tenant_id=None 表示平台管理员，不做租户过滤（查看全部）
        """

        query = db.query(Task)

        if tenant_id:

            query = query.filter(
                Task.tenant_id == tenant_id
            )

        if status:

            query = query.filter(
                Task.status == status
            )

        return (
            query.order_by(Task.deadline.asc(), Task.id.asc())
            .all()
        )

    def list_by_department(
            self,
            db: Session,
            tenant_id: str | None = None,
            department: str = "",
            status: str | None = None
    ) -> list[Task]:

        """
        按部门查任务清单（Enterprise Agent department_tasks）

        tenant_id=None 表示平台管理员，不做租户过滤。
        department 是自由文本（tasks.department 冗余字段），与用户部门字符串匹配。
        TODO(Enterprise)：后续改 department_id 外键后此处改为关联查询
        """

        if not department:
            return []

        query = db.query(Task).filter(
            Task.department == department
        )

        if tenant_id:

            query = query.filter(
                Task.tenant_id == tenant_id
            )

        if status:

            query = query.filter(
                Task.status == status
            )

        return (
            query.order_by(Task.deadline.asc(), Task.id.asc())
            .all()
        )

    def get_employee_tasks(
            self,
            db: Session,
            tenant_id: str,
            employee_id: int,
            status: str | None = None
    ) -> list[Task]:

        query = db.query(Task).filter(
            Task.tenant_id == tenant_id,
            Task.employee_id == employee_id,
        )

        if status:

            query = query.filter(
                Task.status == status
            )

        return (
            query.order_by(Task.deadline.asc(), Task.id.asc())
            .all()
        )

    def get_employee_active_tasks(
            self,
            db: Session,
            tenant_id: str,
            employee_id: int
    ) -> list[Task]:

        """
        员工未完成任务（pending/processing），批量提交用
        """

        return (
            db.query(Task)
            .filter(
                Task.tenant_id == tenant_id,
                Task.employee_id == employee_id,
                Task.status.in_(["pending", "processing"]),
            )
            .order_by(Task.deadline.asc(), Task.id.asc())
            .all()
        )

    def count_by_employee(
            self,
            db: Session,
            employee_id: int
    ) -> int:

        """
        该员工全部租户下的任务数（用户改租户守卫用）
        """

        return (
            db.query(Task)
            .filter(Task.employee_id == employee_id)
            .count()
        )

    def update_progress(
            self,
            db: Session,
            task_id: int,
            progress: int,
            *,
            status: str | None = None
    ) -> Task | None:

        task = db.get(
            Task,
            task_id,
        )

        if not task:

            return None

        progress = max(0, min(100, int(progress)))

        task.progress = progress

        if status:

            task.status = status

        else:

            if progress >= 100:

                task.status = "completed"

            elif task.status == "pending":

                task.status = "processing"

        db.commit()

        db.refresh(task)

        return task

    def list_overdue(
            self,
            db: Session,
            tenant_id: str
    ) -> list[Task]:

        """
        已过截止日期且未完成任务（Phase 3 自动督办用）
        """

        return (
            db.query(Task)
            .filter(
                Task.tenant_id == tenant_id,
                Task.deadline.isnot(None),
                Task.deadline < datetime.now(),
                Task.status.in_(["pending", "processing"]),
            )
            .order_by(Task.deadline.asc())
            .all()
        )

    def list_remindable(
            self,
            db: Session
    ) -> list[Task]:

        """
        每日督办平台扫描：全部租户未完成任务（pending/processing）且含截止日期

        先例：list_by_tenant(tenant_id=None) 已支持平台管理员不按租户过滤。
        返回任务自带 tenant_id，通知侧按 task.tenant_id 隔离（多租户铁律不变）。
        """

        return (
            db.query(Task)
            .filter(
                Task.deadline.isnot(None),
                Task.status.in_(["pending", "processing"]),
            )
            .order_by(Task.deadline.asc())
            .all()
        )

    # ======================
    # 提交记录
    # ======================

    def add_update(
            self,
            db: Session,
            *,
            task_id: int,
            employee_id: int,
            content: str,
            progress: int,
            ai_summary: str = "",
            confirmed: bool = True
    ) -> TaskUpdate:

        record = TaskUpdate(
            task_id=task_id,
            employee_id=employee_id,
            content=content,
            progress=progress,
            ai_summary=ai_summary,
            confirmed=confirmed,
        )

        db.add(record)

        db.commit()

        db.refresh(record)

        return record

    def list_updates(
            self,
            db: Session,
            task_id: int
    ) -> list[TaskUpdate]:

        return (
            db.query(TaskUpdate)
            .filter(TaskUpdate.task_id == task_id)
            .order_by(TaskUpdate.id.desc())
            .all()
        )

    # ======================
    # 待确认状态
    # ======================

    def get_pending(
            self,
            db: Session,
            task_id: int,
            employee_id: int
    ) -> TaskPendingUpdate | None:

        return (
            db.query(TaskPendingUpdate)
            .filter(
                TaskPendingUpdate.task_id == task_id,
                TaskPendingUpdate.employee_id == employee_id,
            )
            .first()
        )

    def get_latest_pending(
            self,
            db: Session,
            tenant_id: str,
            employee_id: int
    ) -> tuple[TaskPendingUpdate | None, Task | None]:

        """
        员工最新的待确认提交（join 任务，校验租户）
        """

        row = (
            db.query(TaskPendingUpdate, Task)
            .join(
                Task,
                Task.id == TaskPendingUpdate.task_id,
            )
            .filter(
                Task.tenant_id == tenant_id,
                TaskPendingUpdate.employee_id == employee_id,
            )
            .order_by(TaskPendingUpdate.id.desc())
            .first()
        )

        if not row:

            return None, None

        return row[0], row[1]

    def list_pendings(
            self,
            db: Session,
            tenant_id: str,
            employee_id: int
    ) -> list[tuple[TaskPendingUpdate, Task]]:

        """
        员工全部待确认提交（join 任务，批量确认用）
        """

        return (
            db.query(TaskPendingUpdate, Task)
            .join(
                Task,
                Task.id == TaskPendingUpdate.task_id,
            )
            .filter(
                Task.tenant_id == tenant_id,
                TaskPendingUpdate.employee_id == employee_id,
            )
            .order_by(TaskPendingUpdate.id.asc())
            .all()
        )

    def upsert_pending(
            self,
            db: Session,
            *,
            task_id: int,
            employee_id: int,
            content: str,
            parsed: dict
    ) -> TaskPendingUpdate:

        pending = self.get_pending(
            db,
            task_id,
            employee_id,
        )

        if pending:

            pending.content = content

            pending.parsed = parsed

            db.commit()

            db.refresh(pending)

            return pending

        pending = TaskPendingUpdate(
            task_id=task_id,
            employee_id=employee_id,
            content=content,
            parsed=parsed,
        )

        db.add(pending)

        db.commit()

        db.refresh(pending)

        return pending

    def clear_pending(
            self,
            db: Session,
            task_id: int,
            employee_id: int
    ) -> None:

        pending = self.get_pending(
            db,
            task_id,
            employee_id,
        )

        if pending:

            db.delete(pending)

            db.commit()
