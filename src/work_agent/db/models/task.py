from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from work_agent.db.base import Base


class TaskNotification(Base):

    """
    任务通知记录表

    记录企微/邮件/系统消息发送状态，用于历史查询、失败重试、统计
    """

    __tablename__ = "task_notifications"

    __table_args__ = (
        Index(
            "ix_task_notifications_task",
            "tenant_id",
            "task_id",
        ),
    )

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True
    )

    tenant_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True
    )

    task_id: Mapped[int] = mapped_column(
        BigInteger,
        index=True
    )

    receiver_id: Mapped[int] = mapped_column(
        BigInteger
    )

    # wechat / email / system
    channel: Mapped[str] = mapped_column(
        String(16),
        default="wechat"
    )

    content: Mapped[str] = mapped_column(
        Text
    )

    # pending / sent / failed
    status: Mapped[str] = mapped_column(
        String(16),
        default="pending"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now()
    )

    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True
    )


class Task(Base):

    """
    任务表
    """

    __tablename__ = "tasks"

    __table_args__ = (
        Index(
            "ix_tasks_tenant_employee",
            "tenant_id",
            "employee_id",
        ),
        Index(
            "ix_tasks_tenant_status",
            "tenant_id",
            "status",
        ),
    )

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True
    )

    # 多租户铁律：tenant_id 必填且不允许空字符串（归属数据所有者=负责人租户）
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True
    )

    title: Mapped[str] = mapped_column(
        String(255)
    )

    description: Mapped[str] = mapped_column(
        Text,
        default=""
    )

    creator_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True
    )

    manager_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        index=True
    )

    employee_id: Mapped[int] = mapped_column(
        BigInteger,
        index=True
    )

    department: Mapped[str] = mapped_column(
        String(64),
        default=""
    )

    deadline: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True
    )

    # pending / processing / completed / overdue
    status: Mapped[str] = mapped_column(
        String(32),
        default="pending"
    )

    # 0-100
    progress: Mapped[int] = mapped_column(
        Integer,
        default=0
    )

    # low / normal / high
    priority: Mapped[str] = mapped_column(
        String(16),
        default="normal"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now()
    )

    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=True
    )


class TaskUpdate(Base):

    """
    员工任务进度提交记录
    """

    __tablename__ = "task_updates"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True
    )

    task_id: Mapped[int] = mapped_column(
        BigInteger,
        index=True
    )

    employee_id: Mapped[int] = mapped_column(
        BigInteger
    )

    content: Mapped[str] = mapped_column(
        Text
    )

    # 0-100
    progress: Mapped[int] = mapped_column(
        Integer,
        default=0
    )

    # AI 解析摘要
    ai_summary: Mapped[str] = mapped_column(
        Text,
        default=""
    )

    # 是否经员工确认后落库
    confirmed: Mapped[bool] = mapped_column(
        Boolean,
        default=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now()
    )


class TaskPendingUpdate(Base):

    """
    待确认提交（AI 解析后、员工确认前）

    员工回复「确认」才写入 task_updates 并更新 tasks.progress
    """

    __tablename__ = "task_pending_updates"

    __table_args__ = (
        UniqueConstraint(
            "task_id",
            "employee_id",
            name="uq_task_pending_task_employee",
        ),
    )

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True
    )

    task_id: Mapped[int] = mapped_column(
        BigInteger,
        index=True
    )

    employee_id: Mapped[int] = mapped_column(
        BigInteger,
        index=True
    )

    # 员工原始反馈
    content: Mapped[str] = mapped_column(
        Text
    )

    # AI 解析结果：{progress, summary, done, remaining}
    parsed: Mapped[dict] = mapped_column(
        JSON,
        default=dict
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now()
    )
