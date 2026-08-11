from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from sqlalchemy.orm import Session

from work_agent.config import settings
from work_agent.repositories.user_repository import UserRepository


class AuthService:

    """
    认证服务：bcrypt 密码哈希 + JWT 令牌
    """

    def __init__(
            self,
            user_repository: UserRepository | None = None
    ):

        self.user_repository = user_repository or UserRepository()


    @staticmethod
    def hash_password(
            password: str
    ) -> str:

        return bcrypt.hashpw(
            password.encode("utf-8"),
            bcrypt.gensalt()
        ).decode("utf-8")


    @staticmethod
    def verify_password(
            password: str,
            password_hash: str
    ) -> bool:

        try:

            return bcrypt.checkpw(
                password.encode("utf-8"),
                password_hash.encode("utf-8")
            )

        except ValueError:
            return False


    @staticmethod
    def create_token(
            user_id: int
    ) -> str:

        expire = (
            datetime.now(timezone.utc)
            + timedelta(minutes=settings.jwt_expire_minutes)
        )

        payload = {
            "sub": str(user_id),
            "exp": expire
        }

        return jwt.encode(
            payload,
            settings.jwt_secret,
            algorithm=settings.jwt_algorithm
        )


    @staticmethod
    def decode_token(
            token: str
    ) -> int | None:

        try:

            payload = jwt.decode(
                token,
                settings.jwt_secret,
                algorithms=[
                    settings.jwt_algorithm
                ]
            )

            return int(
                payload["sub"]
            )

        except (jwt.PyJWTError, KeyError, ValueError):
            return None


    def authenticate(
            self,
            db: Session,
            username: str,
            password: str
    ):

        """
        校验用户名密码，成功返回 User，失败返回 None
        """

        user = self.user_repository.get_by_username(
            db,
            username
        )

        if not user:
            return None

        if not self.verify_password(
                password,
                user.password_hash
        ):
            return None

        return user
