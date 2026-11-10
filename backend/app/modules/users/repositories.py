from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.modules.users.models import User, UserRole


class UserRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_by_email(self, email: str) -> User | None:
        return self.session.scalar(select(User).where(User.email == email))

    def get_by_id(self, user_id: str) -> User | None:
        return self.session.get(User, user_id)

    def has_admin(self) -> bool:
        return (
            self.session.scalar(select(User.id).where(User.role == UserRole.ADMIN).limit(1))
            is not None
        )

    def lock_bootstrap(self) -> None:
        # Serializa o bootstrap, inclusive quando dois comandos iniciam ao mesmo tempo.
        if self.session.get_bind().dialect.name == "sqlite":
            self.session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        else:
            self.session.execute(text("SELECT pg_advisory_xact_lock(78524101)"))

    def add(self, user: User) -> None:
        self.session.add(user)
        self.session.flush()
