from collections.abc import AsyncIterator
from datetime import datetime

from sqlalchemy import DateTime, MetaData, event, func, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, SessionTransaction, mapped_column

from agriverse.config import get_settings

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


settings = get_settings()


class TenantSession(Session):
    """Keep the request's tenant across transactions, never on pooled connections."""


@event.listens_for(TenantSession, "after_begin")
def restore_tenant_context(
    session: Session, transaction: SessionTransaction, connection: Connection
) -> None:
    organization_id = session.info.get("organization_id")
    if organization_id is not None:
        connection.execute(
            text("SELECT set_config('app.org_id', :org_id, true)"),
            {"org_id": str(organization_id)},
        )


engine: AsyncEngine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)
SessionFactory = async_sessionmaker(
    engine, expire_on_commit=False, class_=AsyncSession, sync_session_class=TenantSession
)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionFactory() as session:
        try:
            yield session
        finally:
            await session.close()
