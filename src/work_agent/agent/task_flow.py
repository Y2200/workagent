"""
Task Lifecycle 状态机（Phase 9）

企业任务生命周期：
    CREATED → ASSIGNED → IN_PROGRESS → SUBMITTED → REVIEWED → COMPLETED
    任何阶段 → CANCELLED

实现策略：映射到现有 status 字段（pending/processing/completed/cancelled），
不破坏 stats/reminder/list 过滤。

语义映射：
    CREATED   → "pending"   （任务已创建，未指派）
    ASSIGNED  → "pending"   （已指派给员工，未开始）
    IN_PROGRESS → "processing"（员工开始执行）
    SUBMITTED → "processing"（员工提交结果，待经理确认）
    REVIEWED  → "processing"（经理已确认）
    COMPLETED → "completed"（任务完成）
    CANCELLED → "cancelled"（已取消）

对外 API 用状态机概念（created/assigned/in_progress/submitted/reviewed/
completed/cancelled），落库映射到现有 status 值。
"""

# 业务状态 → 落库 status
STATE_TO_DB = {
    "created": "pending",
    "assigned": "pending",
    "in_progress": "processing",
    "submitted": "processing",
    "reviewed": "processing",
    "completed": "completed",
    "cancelled": "cancelled",
}

# 落库 status → 业务状态（反向映射，取语义代表）
DB_TO_STATE = {
    "pending": "assigned",
    "processing": "in_progress",
    "completed": "completed",
    "cancelled": "cancelled",
}

# 合法转移表：state → 允许转移到的状态集
TRANSITIONS = {
    "created": {"assigned", "cancelled"},
    "assigned": {"in_progress", "cancelled"},
    "in_progress": {"submitted", "completed", "cancelled"},
    "submitted": {"reviewed", "in_progress", "completed", "cancelled"},
    "reviewed": {"completed", "in_progress", "cancelled"},
    "completed": set(),          # 终态
    "cancelled": set(),          # 终态
}

# 可取消的状态（任何非终态）
CANCELLABLE_STATES = {
    "created", "assigned", "in_progress", "submitted", "reviewed",
}

# 未完成状态（统计/督办用）
ACTIVE_DB_STATUSES = ("pending", "processing")


class TaskFlowError(ValueError):
    """非法状态转移"""
    pass


def current_state(db_status: str) -> str:
    """
    当前业务状态（从落库 status 映射）
    """
    return DB_TO_STATE.get(db_status, "created")


def can_transition(from_db_status: str, to_state: str) -> bool:
    """
    判断从当前落库状态能否转移到目标业务状态
    """
    from_state = current_state(from_db_status)

    allowed = TRANSITIONS.get(from_state, set())

    return to_state in allowed


def validate_transition(from_db_status: str, to_state: str) -> str:
    """
    校验并返回转移后的落库状态；非法抛 TaskFlowError
    """
    if to_state not in STATE_TO_DB:
        raise TaskFlowError(f"未知任务状态: {to_state}")

    from_state = current_state(from_db_status)

    allowed = TRANSITIONS.get(from_state, set())

    if to_state not in allowed:
        raise TaskFlowError(
            f"非法状态转移: {from_state} → {to_state}"
            f"（允许: {sorted(allowed)}）"
        )

    return STATE_TO_DB[to_state]


def initial_db_status() -> str:
    """
    新任务初始落库状态（created → pending）
    """
    return STATE_TO_DB["created"]


def is_terminal(db_status: str) -> bool:
    """
    是否终态（completed/cancelled）
    """
    return db_status in ("completed", "cancelled")


def active_db_statuses() -> tuple:
    """
    未完成状态（统计/督办扫描用）
    """
    return ACTIVE_DB_STATUSES
