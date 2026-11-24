"""Migration role is separate from the runtime role; never print connection secrets."""
import os
from alembic import context
from sqlalchemy import create_engine, pool
from portal.models import Base
import portal.batch_models  # Register the independent batch tables for Alembic.
import portal.operations_models

configuration = context.config
url = os.environ.get("MIGRATION_DATABASE_URL") or os.environ["DATABASE_URL"]
if not url.startswith("postgresql+psycopg://"):
    raise RuntimeError("PostgreSQL migrations only")
if context.is_offline_mode():
    context.configure(url=url, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction(): context.run_migrations()
else:
    engine = create_engine(url, poolclass=pool.NullPool, echo=False)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
        with context.begin_transaction(): context.run_migrations()
