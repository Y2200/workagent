from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from work_agent.config import settings


# 同步引擎
# 仅配合 def 端点使用（FastAPI 自动放入线程池）
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_recycle=3600,
    echo=False
)


SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
    class_=Session
)


def get_db():

    """
    FastAPI 数据库依赖

    每次请求独立 Session，请求结束关闭
    """

    db = SessionLocal()

    try:
        yield db

    finally:
        db.close()
