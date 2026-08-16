from work_agent.db.session import SessionLocal
from work_agent.repositories.user_repository import UserRepository


class UserService:

    """
    用户业务服务（Enterprise Agent 工具经此访问用户数据）

    分层铁律：API → Service → Repository → DB。
    工具（user_tool/task_tool 富化姓名）只能经本服务查询，禁止直连 DB。
    """

    def __init__(
            self,
            repository: UserRepository | None = None
    ):

        self.repository = repository or UserRepository()


    def get_by_id(
            self,
            user_id: int
    ):

        db = SessionLocal()

        try:

            return self.repository.get_by_id(
                db,
                user_id,
            )

        finally:

            db.close()


    def search_by_name(
            self,
            *,
            keyword: str,
            tenant_id: str = ""
    ):

        """
        按姓名/账号解析员工（user_tool resolve）
        """

        if not keyword:
            return []

        db = SessionLocal()

        try:

            return self.repository.search_by_name(
                db,
                keyword=keyword,
                tenant_id=tenant_id,
            )

        finally:

            db.close()


    def list_by_department(
            self,
            *,
            department: str,
            tenant_id: str = ""
    ):

        """
        按部门查询用户（user_tool list_department）
        """

        if not department:
            return []

        db = SessionLocal()

        try:

            return self.repository.list_by_department(
                db,
                department=department,
                tenant_id=tenant_id,
            )

        finally:

            db.close()


# 全局单例
user_service = UserService()
