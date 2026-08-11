from typing import Generic, TypeVar

from sqlalchemy.orm import Session

from work_agent.db.base import Base


ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):

    """
    通用 CRUD 基类
    """

    def __init__(self, model: type[ModelT]):

        self.model = model


    def get(
            self,
            db: Session,
            obj_id: int
    ):

        return db.get(
            self.model,
            obj_id
        )


    def list(
            self,
            db: Session,
            offset: int = 0,
            limit: int = 100
    ):

        return (
            db.query(self.model)
            .offset(offset)
            .limit(limit)
            .all()
        )


    def add(
            self,
            db: Session,
            obj
    ):

        db.add(obj)

        db.commit()

        db.refresh(obj)

        return obj


    def delete(
            self,
            db: Session,
            obj
    ) -> None:

        db.delete(obj)

        db.commit()
