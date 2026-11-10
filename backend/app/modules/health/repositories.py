from sqlalchemy import text
from sqlalchemy.orm import Session


class HealthRepository:
    def __init__(self, session: Session):
        self.session = session

    def ping(self) -> bool:
        return self.session.execute(text("SELECT 1")).scalar_one() == 1
