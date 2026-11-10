from sqlalchemy.exc import IntegrityError

from app.core.errors import ApplicationError
from app.core.security import hash_password
from app.modules.users.models import User, UserRole
from app.modules.users.repositories import UserRepository
from app.modules.users.schemas import AdminCreate, UserPublic


class UserService:
    def __init__(self, repository: UserRepository):
        self.repository = repository

    def bootstrap_admin(self, data: AdminCreate) -> UserPublic:
        hashed = hash_password(data.password.get_secret_value())
        try:
            with self.repository.session.begin():
                self.repository.lock_bootstrap()
                if self.repository.has_admin():
                    raise ApplicationError(
                        "admin_exists", "O administrador inicial já foi cadastrado.", 409
                    )
                user = User(
                    name=data.name,
                    email=str(data.email),
                    password_hash=hashed,
                    role=UserRole.ADMIN,
                    is_active=True,
                )
                self.repository.add(user)
                result = UserPublic.model_validate(user)
            return result
        except IntegrityError as exc:
            raise ApplicationError(
                "user_conflict", "Não foi possível cadastrar: e-mail já utilizado.", 409
            ) from exc
