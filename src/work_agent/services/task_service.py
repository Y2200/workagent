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


def _normalize_title(
        title: str
) -> str:
    """
    归一化任务名用于精确匹配（去空格/大小写/常见后缀）
    """

    text = title.strip().lower()

    for suffix in ("任务", "项目", "工作", "的"):

        if text.endswith(suffix):

            text = text[:-len(suffix)].strip()

    return text


def _cosine(
        a,
        b
) -> float:

    """
    余弦相似度
    """

    dot = sum(x * y for x, y in zip(a, b))

    norm_a = sum(x * x for x in a) ** 0.5

    norm_b = sum(x * x for x in b) ** 0.5

    if norm_a == 0 or norm_b == 0:

        return 0.0

    return dot / (norm_a * norm_b)


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

    def transition(
            self,
            *,
            tenant_id: str | None,
            task_id: int,
            to_state: str,
            actor_id: int | None = None
    ) -> dict:

        """
        统一任务状态转移（Task Lifecycle，Phase 9）

        经 task_flow 状态机校验合法转移，再更新 status。
        tenant_id=None 表示平台管理员跳过校验。

        返回：
            {"status": "transitioned", "task": {...}}
            或 {"status": "invalid_transition", "message": ...}
        """

        from work_agent.agent.task_flow import (
            TaskFlowError,
            validate_transition,
        )

        db = SessionLocal()

        try:

            task = self.repository.get_by_id(
                db,
                task_id,
            )

            if not task:

                return {
                    "status": "error",
                    "message": f"任务不存在: {task_id}",
                }

            if tenant_id and task.tenant_id != tenant_id:

                raise TenantAccessDenied(
                    "跨租户访问任务"
                )

            # 状态机校验（映射现有字段，不破坏 stats/reminder）
            try:

                new_db_status = validate_transition(
                    task.status,
                    to_state,
                )

            except TaskFlowError as exc:

                return {
                    "status": "invalid_transition",
                    "message": str(exc),
                    "current": task.status,
                }

            task.status = new_db_status

            db.commit()

            db.refresh(task)

            return {
                "status": "transitioned",
                "task": self._task_dict(task),
                "to_state": to_state,
            }

        finally:

            db.close()

    def cancel_task(
            self,
            *,
            tenant_id: str | None,
            task_id: int,
            actor_id: int | None = None
    ) -> dict:

        """
        取消任务（任何非终态 → cancelled）
        """

        return self.transition(
            tenant_id=tenant_id,
            task_id=task_id,
            to_state="cancelled",
            actor_id=actor_id,
        )

    def get_task(
            self,
            *,
            tenant_id: str | None,
            task_id: int
    ):

        """
        tenant_id=None 表示平台管理员，跳过租户校验
        """

        db = SessionLocal()

        try:

            task = self.repository.get_by_id(
                db,
                task_id,
            )

            if (
                task
                and tenant_id
                and task.tenant_id != tenant_id
            ):

                raise TenantAccessDenied(
                    "跨租户访问任务"
                )

            return task

        finally:

            db.close()

    def list_tasks_for_web(
            self,
            *,
            tenant_id: str | None = None,
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

    def list_tasks_by_department(
            self,
            *,
            tenant_id: str | None,
            department: str,
            status: str | None = None
    ):

        """
        按部门查任务清单（Enterprise Agent department_tasks）

        tenant_id=None 平台管理员全量；department 自由文本匹配。
        """

        db = SessionLocal()

        try:

            return self.repository.list_by_department(
                db,
                tenant_id=tenant_id,
                department=department,
                status=status,
            )

        finally:

            db.close()

    def get_employee_task_by_title(
            self,
            *,
            tenant_id: str,
            employee_id: int,
            title: str
    ):

        """
        在员工任务中按标题查找任务（精确 + 归一化）
        """

        if not title:

            return None

        db = SessionLocal()

        try:

            tasks = self.repository.get_employee_tasks(
                db,
                tenant_id,
                employee_id,
            )

            norm = _normalize_title(title)

            # 归一化完全匹配（不做简单 contains）
            for task in tasks:

                if _normalize_title(task.title) == norm:

                    return task

            return None

        finally:

            db.close()

    def resolve_task_from_message(
            self,
            *,
            tenant_id: str,
            employee_id: int,
            message: str
    ):

        """
        任务上下文优先：短消息匹配员工任务名 → 返回任务

        匹配优先级：
        1. 归一化完全匹配任务名
        2. 当前用户任务（即最近任务）
        3. embedding 相似匹配（阈值 0.75）
        4. （LLM 判断留待后续，当前由 IntentRouter 兜底）

        仅处理短消息（任务名长度内），长句交给意图路由
        """

        msg = message.strip()

        # 仅处理纯任务名长度的短消息
        if not (1 <= len(msg) <= 16):

            return None

        # 含动作词（提交/进度/完成/确认等）→ 交给常规意图路由（submit/list 等）
        if any(
                word in msg
                for word in ("提交", "进度", "完成", "确认", "取消", "查看", "我的")
        ):

            return None

        task = self.get_employee_task_by_title(
            tenant_id=tenant_id,
            employee_id=employee_id,
            title=msg,
        )

        if task:

            return task

        # embedding 相似匹配（复用 bge 模型，失败静默）
        try:

            from work_agent.core.container import rag_service

            vec = rag_service.embedding.encode(
                [msg]
            )[0]

            best = None

            best_score = 0.0

            for t in self.list_employee_tasks(
                    tenant_id=tenant_id,
                    employee_id=employee_id,
            ):

                title_vec = rag_service.embedding.encode(
                    [t.title]
                )[0]

                score = _cosine(vec, title_vec)

                if score > best_score:

                    best = t

                    best_score = score

            if best and best_score >= 0.75:

                return best

        except Exception:

            pass

        return None

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

            # 兜底清理：summary 不应包含任务名（LLM 偶发把任务名当摘要）
            summary = parsed.get("summary", "")

            if task.title and task.title in summary:

                cleaned = (
                    summary.replace(task.title, "")
                    .strip(" ，,。")
                )

                parsed["summary"] = (
                    cleaned
                    or "未提供具体完成内容"
                )

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

    def submit_all_progress(
            self,
            *,
            tenant_id: str,
            employee_id: int,
            content: str
    ) -> dict:

        """
        批量提交：给员工全部未完成任务创建待确认（同一进度）

        返回：
        {"status": "awaiting_confirmation", "progress": N, "tasks": [...], "summary": "..."}
        或 {"status": "no_tasks", "message": "..."}
        """

        db = SessionLocal()

        try:

            tasks = self.repository.get_employee_active_tasks(
                db,
                tenant_id,
                employee_id,
            )

            if not tasks:

                return {
                    "status": "no_tasks",
                    "message": "你目前没有进行中的任务。",
                }

            progress = self._extract_progress(content)

            summary = "批量进度更新"

            items = []

            for task in tasks:

                parsed = {
                    "progress": progress,
                    "summary": summary,
                    "done": [],
                    "remaining": [],
                }

                self.repository.upsert_pending(
                    db,
                    task_id=task.id,
                    employee_id=employee_id,
                    content=content,
                    parsed=parsed,
                )

                items.append(
                    {
                        "id": task.id,
                        "title": task.title,
                    }
                )

            return {
                "status": "awaiting_confirmation",
                "progress": progress,
                "summary": summary,
                "tasks": items,
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
        员工确认：全部待确认 pending → task_updates + tasks.progress

        支持单个与批量（批量 = 员工有多条 pending）

        返回：
        {"status": "confirmed", "count": N, "items": [{task, progress, summary}...]}
        或 {"status": "no_pending", "message": "..."}
        """

        db = SessionLocal()

        try:

            rows = self.repository.list_pendings(
                db,
                tenant_id,
                employee_id,
            )

            if not rows:

                return {
                    "status": "no_pending",
                    "message": "当前没有待确认的提交。",
                }

            items = []

            for pending, task in rows:

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

                updated = self.repository.update_progress(
                    db,
                    task.id,
                    progress,
                )

                self.repository.clear_pending(
                    db,
                    task.id,
                    employee_id,
                )

                # 任务完成 → 邮件通知创建者/主管（失败不影响主流程，Phase 4）
                if updated and updated.status == "completed":

                    try:

                        from work_agent.services.notification_service import (
                            notification_service,
                        )

                        notification_service.send_task_completed_email(
                            updated
                        )

                    except Exception:

                        pass

                items.append(
                    {
                        "task": self._task_dict(task),
                        "progress": progress,
                        "summary": summary,
                    }
                )

            return {
                "status": "confirmed",
                "count": len(items),
                "items": items,
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
    # 任务创建草稿（Enterprise Agent Phase 3，带确认）
    # ======================

    def preview_create_task(
            self,
            *,
            creator_id: int,
            creator_tenant_id: str,
            content: str,
            chat_history=None
    ) -> dict:

        """
        解析任务创建消息 → 生成待确认草稿（不落正式表）

        解析职责划分（用户要求）：
        - 执行人：DB 确定性查询（UserRepository.search_by_name），LLM 不负责
        - 截止时间：代码规则优先（_parse_deadline_text）
        - LLM 仅补充描述/标题/优先级字段（prompt task_create_parse）

        chat_history（可选）：会话上下文，只辅助 LLM 理解
        （如"按照这个制度给张三安排任务"的"这个制度"）；
        不参与 employee_id/deadline/RBAC 等业务决策。

        返回：
            awaiting_confirmation / need_info / employee_not_found
        """

        if not content or not content.strip():

            return {
                "status": "need_info",
                "message": "请提供任务信息，例如「给张三安排客户系统测试任务，下周五完成」",
                "missing": ["title", "employee_name"],
            }

        parsed = self._parse_create_message(
            content,
            chat_history,
        )

        title = (parsed.get("title") or "").strip()

        employee_name = (parsed.get("employee_name") or "").strip()

        deadline_text = (parsed.get("deadline_text") or "").strip()

        # 在途草稿（多轮补充：上一条缺字段的部分信息保留，本轮合并续补）
        from work_agent.core.container import user_service

        pending = self._get_active_pending_create(creator_id)

        # 补充回复判定：短消息（≤12 字、无任务指令词），如「张三」「客户系统测试」。
        # 只有补充回复才合并续补在途草稿；含任务词的完整消息一律视为全新创建
        # （避免「我想发布一个新任务」误沿用上一条草稿的执行人）。
        candidate = content.strip()

        is_supplement = (
            pending is not None
            and len(candidate) <= 12
            and not re.search(
                r"任务|发布|安排|创建|新增|分派|指派|做|完成"
                r"|查看|查询|看看|名单|部门|有哪些|谁|怎么|如何|成员",
                candidate,
            )
        )

        resolved_employee_id = None

        if is_supplement:

            consumed_as_name = False

            # 1) 缺执行人 → 短消息优先当作姓名补全
            if not employee_name and pending.employee_id is None:

                candidate_users = user_service.search_by_name(
                    keyword=candidate,
                    tenant_id=(
                        creator_tenant_id
                        if creator_tenant_id
                        else ""
                    ),
                )

                if len(candidate_users) == 1:

                    employee_name = (
                        candidate_users[0].real_name
                        or candidate_users[0].username
                    )

                    resolved_employee_id = candidate_users[0].id

                    consumed_as_name = True

                elif len(candidate_users) > 1:

                    self._save_partial_pending(
                        creator_id=creator_id,
                        creator_tenant_id=creator_tenant_id,
                        title=title,
                        employee_id=None,
                        deadline_text=deadline_text,
                        parsed=parsed,
                        content=content,
                    )

                    return {
                        "status": "employee_not_found",
                        "message": (
                            f"「{candidate}」匹配到多个员工，"
                            "请补充更完整姓名"
                            "（可回复「查看本部门员工」查看名单）"
                        ),
                        "parsed": parsed,
                        "candidates": [
                            {
                                "id": u.id,
                                "real_name": u.real_name or u.username,
                                "department": u.department or "",
                            }
                            for u in candidate_users
                        ],
                    }

                else:

                    # 非姓名：缺标题则当标题，否则提示未找到
                    if not title and not pending.title:

                        title = candidate

                    else:

                        self._save_partial_pending(
                            creator_id=creator_id,
                            creator_tenant_id=creator_tenant_id,
                            title=title,
                            employee_id=None,
                            deadline_text=deadline_text,
                            parsed=parsed,
                            content=content,
                        )

                        return {
                            "status": "employee_not_found",
                            "message": (
                                f"未找到员工「{candidate}」，"
                                "请确认姓名"
                                "（可回复「查看本部门员工」查看名单）"
                            ),
                            "parsed": parsed,
                        }

            # 2) 缺标题 → 短消息当标题（未被当姓名消费时）
            if (
                not consumed_as_name
                and not title
                and not pending.title
            ):

                title = candidate

            # 3) 继承草稿其余字段（姓名被消费时标题必须来自草稿）
            if consumed_as_name or not title:
                title = pending.title or ""

            if not employee_name and pending.employee_id:

                emp = user_service.get_by_id(
                    pending.employee_id,
                )

                if emp:
                    employee_name = (
                        emp.real_name
                        or emp.username
                    )
                    resolved_employee_id = pending.employee_id

            if not deadline_text:
                deadline_text = (
                    pending.parsed or {}
                ).get(
                    "deadline_text",
                    "",
                )

        # 1. 缺关键字段 → 追问（落部分草稿，供下一轮合并）
        missing = []

        if not title:
            missing.append("title")

        if not employee_name:
            missing.append("employee_name")

        if missing:

            self._save_partial_pending(
                creator_id=creator_id,
                creator_tenant_id=creator_tenant_id,
                title=title,
                employee_id=resolved_employee_id,
                deadline_text=deadline_text,
                parsed=parsed,
                content=content,
            )

            return {
                "status": "need_info",
                "missing": missing,
                "parsed": parsed,
                "message": (
                    "我需要补充："
                    + ("任务名称；" if "title" in missing else "")
                    + ("执行人；" if "employee_name" in missing else "")
                    + "请补充后继续。"
                ),
            }

        # 2. 执行人 DB 确定性解析
        if resolved_employee_id:

            employee = user_service.get_by_id(
                resolved_employee_id,
            )

        else:

            users = user_service.search_by_name(
                keyword=employee_name,
                tenant_id=(
                    creator_tenant_id
                    if creator_tenant_id
                    else ""
                ),
            )

            if not users:

                return {
                    "status": "employee_not_found",
                    "message": (
                        f"未找到员工「{employee_name}」，请确认姓名"
                    ),
                    "parsed": parsed,
                }

            if len(users) > 1:

                return {
                    "status": "employee_not_found",
                    "message": (
                        f"「{employee_name}」匹配到多个员工，"
                        "请补充更完整姓名"
                    ),
                    "parsed": parsed,
                    "candidates": [
                        {
                            "id": u.id,
                            "real_name": u.real_name or u.username,
                            "department": u.department or "",
                        }
                        for u in users
                    ],
                }

            employee = users[0]

        # 3. 截止时间代码规则优先
        deadline = self._parse_deadline_text(deadline_text)

        # 4. 落草稿（在途唯一）
        db = SessionLocal()

        try:

            pending = self.repository.upsert_pending_create(
                db,
                creator_id=creator_id,
                creator_tenant_id=creator_tenant_id,
                employee_id=employee.id,
                title=title,
                description=parsed.get("description") or "",
                department=employee.department or "",
                deadline=deadline,
                priority=parsed.get("priority") or "normal",
                raw_message=content,
                parsed={
                    "employee_name": employee_name,
                    "deadline_text": deadline_text,
                    "deadline_parsed": bool(deadline),
                },
            )

        finally:

            db.close()

        draft = {
            "employee_id": employee.id,
            "employee_name": employee.real_name or employee.username,
            "department": employee.department or "",
            "title": title,
            "description": parsed.get("description") or "",
            "deadline": (
                deadline.isoformat()
                if deadline
                else None
            ),
            "deadline_text": deadline_text,
            "priority": parsed.get("priority") or "normal",
        }

        return {
            "status": "awaiting_confirmation",
            "message": (
                f"我识别到任务：\n"
                f"执行人：{draft['employee_name']}\n"
                f"任务：{draft['title']}\n"
                + (
                    f"截止时间：{deadline_text or '未确定'}\n"
                )
                + f"回复「确认」创建，或「取消」放弃。"
            ),
            "draft": draft,
            "pending_id": pending.id,
        }

    def _get_active_pending_create(
            self,
            creator_id: int
    ):

        """
        读取创建者在途草稿（多轮补充状态）
        """

        db = SessionLocal()

        try:

            return self.repository.get_active_pending_create(
                db,
                creator_id,
            )

        finally:

            db.close()

    def has_incomplete_pending_create(
            self,
            creator_id: int
    ) -> bool:

        """
        是否存在「未完成」的在途创建草稿（缺执行人或任务名）

        供意图路由判断「补充回复」（如补执行人回「张三」）：
        只有草稿缺字段时才把短消息路由到 create 合并续补。
        """

        pending = self._get_active_pending_create(
            creator_id,
        )

        return bool(
            pending
            and not (pending.employee_id and pending.title)
        )

    def _save_partial_pending(
            self,
            *,
            creator_id: int,
            creator_tenant_id: str,
            title: str,
            employee_id: int | None,
            deadline_text: str,
            parsed: dict,
            content: str,
    ) -> None:

        """
        保存部分草稿（缺字段时），使下一轮可合并续补
        """

        db = SessionLocal()

        try:

            self.repository.upsert_pending_create(
                db,
                creator_id=creator_id,
                creator_tenant_id=creator_tenant_id,
                employee_id=employee_id,
                title=title or "",
                description=parsed.get("description") or "",
                deadline=(
                    self._parse_deadline_text(deadline_text)
                    if deadline_text
                    else None
                ),
                priority=parsed.get("priority") or "normal",
                raw_message=content,
                parsed=dict(parsed or {}),
            )

        finally:

            db.close()

    def confirm_pending_create(
            self,
            *,
            creator_id: int
    ) -> dict | None:

        """
        确认创建在途草稿 → create_task 落库（多租户铁律：tenant 归执行人）

        无在途草稿返回 None（task_tool 将回退到进度确认）
        """

        db = SessionLocal()

        try:

            pending = self.repository.get_active_pending_create(
                db,
                creator_id,
            )

            if not pending:
                return None

            if not pending.employee_id or not pending.title:

                self.repository.mark_pending_create(
                    db,
                    pending,
                    "cancelled",
                )

                return {
                    "status": "error",
                    "message": "草稿缺少执行人或任务名，已取消",
                }

            # create_task 内部再查一次执行人（含租户归属）
            task = self.create_task(
                creator_tenant_id=pending.creator_tenant_id,
                title=pending.title,
                description=pending.description,
                creator_id=pending.creator_id,
                employee_id=pending.employee_id,
                department=pending.department or "",
                deadline=pending.deadline,
                priority=pending.priority,
            )

            # 归档草稿（保留历史，允许再建新草稿）
            self.repository.mark_pending_create(
                db,
                pending,
                "confirmed",
            )

            return {
                "status": "task_created",
                "task": self._task_dict(task),
                "message": (
                    f"任务已创建：{task.title}，"
                    "已通知负责人。"
                ),
            }

        except ValueError as exc:

            return {
                "status": "error",
                "message": str(exc),
            }

        finally:

            db.close()

    def cancel_pending_create(
            self,
            *,
            creator_id: int
    ) -> dict | None:

        """
        取消在途创建草稿；无草稿返回 None
        """

        db = SessionLocal()

        try:

            pending = self.repository.get_active_pending_create(
                db,
                creator_id,
            )

            if not pending:
                return None

            self.repository.mark_pending_create(
                db,
                pending,
                "cancelled",
            )

            return {
                "status": "cancelled_create",
                "message": "已取消任务创建。",
            }

        finally:

            db.close()

    def get_active_create_draft(
            self,
            *,
            creator_id: int
    ) -> dict | None:

        """
        查询在途创建草稿（task_agent 展示用）
        """

        db = SessionLocal()

        try:

            pending = self.repository.get_active_pending_create(
                db,
                creator_id,
            )

            if not pending:
                return None

            return {
                "id": pending.id,
                "title": pending.title,
                "employee_id": pending.employee_id,
                "deadline": (
                    pending.deadline.isoformat()
                    if pending.deadline
                    else None
                ),
                "priority": pending.priority,
                "message": (
                    f"存在待确认的任务创建：{pending.title}，"
                    "回复「确认」创建，或「取消」放弃。"
                ),
            }

        finally:

            db.close()

    # ======================
    # 内部：AI 解析（任务创建）
    # ======================

    def _parse_create_message(
            self,
            content: str,
            chat_history=None
    ) -> dict:

        """
        解析任务创建消息（用户要求：执行人与日期确定性，LLM 只补描述）

        解析职责划分：
        - 执行人：确定性正则提取（_fallback_create_parse），LLM 不负责
        - 截止时间：原文保留，由 _parse_deadline_text 确定性解析
        - LLM 仅补充 title/description/priority（失败回退确定性）
        - chat_history：只辅助 LLM 理解上下文，不参与业务决策
        """

        # 先确定性提取执行人/截止（不依赖 LLM，稳定）
        base = self._fallback_create_parse(content)

        employee_name = (
            base.get("employee_name")
            or ""
        ).strip()

        deadline_text = (
            base.get("deadline_text")
            or ""
        ).strip()

        # LLM 只补 title/description/priority（执行人/截止已确定，不覆盖）
        extra = self._llm_create_extra(
            content,
            chat_history,
        )

        # 标题：确定性提取优先（LLM 输出不稳定，避免覆盖正确解析）；
        # LLM 仅在确定性为空时补充
        title = (
            base.get("title")
            or extra.get("title")
            or ""
        ).strip()

        # 执行人/截止确定性覆盖 LLM（用户要求：这两项系统负责）
        return {
            "employee_name": employee_name,
            "title": title,
            "deadline_text": deadline_text,
            "priority": (
                extra.get("priority")
                or "normal"
            ),
            "description": (
                extra.get("description")
                or base.get("description")
                or ""
            ),
        }

    def _llm_create_extra(
            self,
            content: str,
            chat_history=None
    ) -> dict:

        """
        LLM 仅补充 title/description/priority（不解析执行人与日期）

        chat_history（可选）作为对话上下文辅助 LLM 理解
        （如"按照这个制度给张三安排任务"中的"这个制度"指上一轮制度）；
        只辅助理解，不参与执行人/日期/RBAC 等业务决策。
        失败回退确定性提取的 title/description。
        """

        try:

            from work_agent.agent.llm import get_llm

            from work_agent.core.prompt_manager import prompt_manager

            from work_agent.core.utils import parse_json

            from work_agent.services.conversation_memory_service import (
                conversation_memory_service,
            )

            loaded = prompt_manager.load(
                "task_create_parse"
            )

            history_text = (
                conversation_memory_service.serialize_history(
                    chat_history
                )
                if chat_history
                else ""
            )

            result = get_llm().invoke(
                loaded["content"].format(
                    message=content,
                    history=history_text,
                )
            )

            data = parse_json(
                result.content
            )

            return {
                "title": (
                    data.get("title", "")
                    or ""
                ),
                "priority": (
                    data.get("priority", "normal")
                    or "normal"
                ),
                "description": (
                    data.get("description", "")
                    or ""
                ),
            }

        except Exception:

            base = self._fallback_create_parse(content)

            return {
                "title": base.get("title", ""),
                "priority": "normal",
                "description": base.get("description", ""),
            }

    @staticmethod
    @staticmethod
    def _extract_employee_name(
            content: str
    ) -> str:

        """
        确定性提取执行人姓名（多 pattern 顺序尝试，首个命中即取）

        覆盖句式：
        1. 给/安排/让/分派/指派 + 姓名 + 动作/任务（原句式）
        2. 发布/创建/新增…任务 + 给 + 姓名（如「发布任务给张三做…」）
        3. 任务/活 + 给/派给 + 姓名（如「任务给张三」）
        4. 执行人/负责人 + [:] + 姓名（如「执行人：张三」）
        5. 行首姓名 + 负责/来做/跟进/牵头（如「张三负责客户系统测试」）
        """

        patterns = [
            re.compile(
                r"(?:给|安排|让|分派|指派)\s*"
                r"(?!(?:一个|一些|这个|那个|个|下|所有))\s*"
                r"([一-龥A-Za-z]{2,12}?)"
                r"(?=安排|发布|分派|指派|做|完成|开发|测试|任务|"
                r"负责|跟进|牵头|执行|，|,|。|的|了)"
            ),
            re.compile(
                r"(?:发布|创建|新增|新建|下发)\s*(?:任务|活|事项)?\s*"
                r"(?:给|派给|分给|安排给|交办给)\s*"
                r"([一-龥A-Za-z]{2,12})"
            ),
            re.compile(
                r"(?:任务|活|事项)\s*(?:给|派给|分给|安排给)\s*"
                r"([一-龥A-Za-z]{2,12})"
            ),
            re.compile(
                r"(?:执行人|负责人)\s*[:：]?\s*"
                r"([一-龥A-Za-z]{2,12})"
            ),
            re.compile(
                r"(?:^|[，,。；;、])\s*([一-龥A-Za-z]{2,5}?)\s*"
                r"(?:负责|来做|跟进|牵头|执行)"
            ),
        ]

        for pat in patterns:

            match = pat.search(content)

            if match:
                return match.group(1)

        return ""

    @staticmethod
    def _fallback_create_parse(
            content: str
    ) -> dict:

        """
        确定性回退：提取执行人（多句式）+ 任务名
        """

        title = ""

        employee_name = ""

        deadline_text = ""

        employee_name = TaskService._extract_employee_name(content)

        # 截止：匹配「今天/明天/后天/下周X/X天后/尽快/X月X日/YYYY-MM-DD」
        match = re.search(
            r"(?:下?周[一二三四五六日天]"
            r"|今[天日]|明[天日]|后[天日]"
            r"|\d+\s*天后?"
            r"|尽快|越快越好"
            r"|\d{1,2}月\d{1,2}[日号]"
            r"|\d{4}-\d{1,2}-\d{1,2})",
            content,
        )

        if match:
            deadline_text = match.group(0)

        # 任务名：去掉执行人/指令/截止后的剩余文本
        title_text = content

        if employee_name:
            title_text = title_text.replace(
                employee_name,
                "",
            )

        for prefix in (
            "给", "安排", "让", "分派", "指派", "完成", "做",
            "任务", "发布", "创建", "新增", "下发", "负责",
            "执行人", "负责人", "一个",
        ):

            title_text = title_text.replace(
                prefix,
                "",
            )

        if deadline_text:
            title_text = title_text.replace(
                deadline_text,
                "",
            )

        title_text = title_text.strip(" ，,。！!的::：前")

        if title_text:
            title = title_text[:50]

        return {
            "employee_name": employee_name,
            "title": title,
            "deadline_text": deadline_text,
            "priority": "normal",
            "description": content,
        }

    @staticmethod
    def _parse_deadline_text(
            deadline_text: str
    ) -> datetime | None:

        """
        截止时间确定性解析（代码规则优先，LLM 不负责）

        支持：今天/明天/后天/下周X/X天后/X月X日/尽快 → datetime
        无法解析返回 None（草稿保留原文，确认时缺截止也可创建）
        """

        from datetime import timedelta

        if not deadline_text or not deadline_text.strip():

            return None

        text = deadline_text.strip()

        now = datetime.now()

        # 星期映射
        weekday_map = {
            "一": 0,
            "二": 1,
            "三": 2,
            "四": 3,
            "五": 4,
            "六": 5,
            "日": 6,
            "天": 6,
        }

        if text == "尽快" or text == "越快越好":
            return now + timedelta(days=1)

        if text in ("今天", "今日"):
            return now.replace(
                hour=18,
                minute=0,
                second=0,
                microsecond=0,
            )

        if text in ("明天", "明日"):
            return (
                now + timedelta(days=1)
            ).replace(
                hour=18,
                minute=0,
                second=0,
                microsecond=0,
            )

        if text in ("后天",):
            return (
                now + timedelta(days=2)
            ).replace(
                hour=18,
                minute=0,
                second=0,
                microsecond=0,
            )

        # 下周X
        match = re.match(
            r"^下周([一二三四五六日天])$",
            text,
        )

        if match:

            target = weekday_map.get(match.group(1))

            if target is not None:

                days = (target - now.weekday() + 7) % 7
                if days == 0:
                    days = 7
                return (
                    now + timedelta(days=days)
                ).replace(
                    hour=18,
                    minute=0,
                    second=0,
                    microsecond=0,
                )

        # X天后
        match = re.match(
            r"^(\d+)\s*天?后$",
            text,
        )

        if match:

            days = int(match.group(1))

            return (
                now + timedelta(days=days)
            ).replace(
                hour=18,
                minute=0,
                second=0,
                microsecond=0,
            )

        # X月X日（本年）
        match = re.match(
            r"^(\d{1,2})月(\d{1,2})[日号]$",
            text,
        )

        if match:

            try:

                return datetime(
                    now.year,
                    int(match.group(1)),
                    int(match.group(2)),
                    18,
                    0,
                    0,
                )

            except ValueError:
                return None

        # ISO 或 YYYY-MM-DD
        try:

            return datetime.fromisoformat(text)

        except ValueError:
            pass

        return None

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

        # 摘取实际完成内容：去掉任务名 + 「提交/更新」指令 + 「完成X%」框架
        summary = content

        if task_title:

            summary = summary.replace(
                task_title,
                "",
            )

        summary = re.sub(
            r"^\s*(提交|更新)\s*",
            "",
            summary,
        )

        # 只剥开头的「完成X%」框架，保留其后真正的完成内容
        summary = re.sub(
            r"^\s*(已?完成)?\s*\d{1,3}\s*[%％]",
            "",
            summary,
        )

        summary = summary.strip(" ，,。")

        if not summary:

            summary = "未提供具体完成内容"

        return {
            "task_title": task_title,
            "progress": progress,
            "summary": summary,
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
