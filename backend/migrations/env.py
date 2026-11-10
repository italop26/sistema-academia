from alembic import context
from sqlalchemy import create_engine, pool

from app.core.config import get_settings
from app.models import Base
from app.modules.users import models as user_models  # noqa: F401

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
