import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from app.assets import models as asset_models  # noqa: F401
from app.config.settings import get_settings
from app.costs import models as cost_models  # noqa: F401
from app.database.base import Base
from app.finalization import models as finalization_models  # noqa: F401
from app.generation import models as generation_models  # noqa: F401
from app.projects import models  # noqa: F401
from app.quality import models as quality_models  # noqa: F401
from app.storyboards import models as storyboard_models  # noqa: F401
from app.storytelling import models as storytelling_models  # noqa: F401
from app.video_generation import models as video_generation_models  # noqa: F401
from app.visual_bible import models as visual_bible_models  # noqa: F401
from app.workflows import models as workflow_models  # noqa: F401

config = context.config
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: object) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
