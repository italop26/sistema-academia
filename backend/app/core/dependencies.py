from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.database import get_business_session
from app.modules.auth.dependencies import require_admin
from app.modules.users.models import User

BusinessSession = Annotated[Session, Depends(get_business_session)]
Admin = Annotated[User, Depends(require_admin)]
