"""Read-only PostgreSQL regression checks; no administrative role is needed."""

import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from agriverse.config import get_settings
from agriverse.db import TenantSession
from agriverse.dependencies import set_tenant_context
from agriverse.models import Farm, Organization

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_DB_INTEGRATION") != "1",
        reason="runtime database integration is opt-in",
    ),
]

TENANT = text("SELECT current_setting('app.org_id', true)")


@pytest_asyncio.fixture
async def sessions():
    engine = create_async_engine(get_settings().database_url, pool_size=1, max_overflow=0)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False, sync_session_class=TenantSession)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_tenant_survives_commit_rollback_and_explicit_switch(sessions):
    org_a, org_b = uuid.uuid4(), uuid.uuid4()
    async with sessions() as db:
        await set_tenant_context(db, org_a)
        await db.commit()
        assert await db.scalar(TENANT) == str(org_a)
        await db.rollback()
        assert await db.scalar(TENANT) == str(org_a)
        await set_tenant_context(db, org_b)
        assert await db.scalar(TENANT) == str(org_b)
        await db.commit()
        assert await db.scalar(TENANT) == str(org_b)


@pytest.mark.asyncio
async def test_tenant_does_not_leak_to_another_session_on_same_connection(sessions):
    async with sessions() as db:
        await set_tenant_context(db, uuid.uuid4())
        original_pid = await db.scalar(text("SELECT pg_backend_pid()"))
        await db.commit()
    async with sessions() as db:
        assert await db.scalar(text("SELECT pg_backend_pid()")) == original_pid
        assert await db.scalar(TENANT) in (None, "")
        assert list((await db.scalars(select(Farm.id))).all()) == []


@pytest.mark.asyncio
async def test_existing_farm_refresh_after_commit_with_runtime_rls(sessions):
    async with sessions() as db:
        organizations = list((await db.scalars(select(Organization.id))).all())
        for organization_id in organizations:
            await set_tenant_context(db, organization_id)
            farm = await db.scalar(select(Farm).limit(1))
            if farm is None:
                continue
            farm_id = farm.id
            await db.commit()
            await db.refresh(farm)
            assert farm.id == farm_id
            assert farm.organization_id == organization_id
            break
        else:
            pytest.skip("an existing farm is required for the read-only refresh check")
