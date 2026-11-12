from alembic import context
from sqlalchemy import create_engine, pool

from app.core.config import get_settings
from app.models import Base
from app.modules.absence import models as absence_models  # noqa: F401
from app.modules.attendance import models as attendance_models  # noqa: F401
from app.modules.audit import models as audit_models  # noqa: F401
from app.modules.billing import models as billing_models  # noqa: F401
from app.modules.enrollments import models as enrollment_models  # noqa: F401
from app.modules.notifications import models as notification_models  # noqa: F401
from app.modules.payments import models as payment_models  # noqa: F401
from app.modules.plans import models as plan_models  # noqa: F401
from app.modules.students import models as student_models  # noqa: F401
from app.modules.users import models as user_models  # noqa: F401
from app.modules.webhooks import models as webhook_models  # noqa: F401

# Importar aqui os models dos módulos para registrar seu metadata, sem imports circulares.
target_metadata = Base.metadata
url = get_settings().database_url

if context.is_offline_mode():
    context.configure(
        url=url, target_metadata=target_metadata, literal_binds=True, compare_type=True
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
