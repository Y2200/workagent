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
