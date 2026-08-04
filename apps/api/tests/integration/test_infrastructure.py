import os
import uuid
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest
from redis.asyncio import Redis

from agriverse.config import get_settings
from agriverse.services.storage import ObjectNotFoundError, storage

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_INFRA_INTEGRATION") != "1",
        reason="central infrastructure integration is opt-in",
    ),
]


def asyncpg_dsn(database_url: str, *, username: str | None = None) -> str:
    normalized = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    if username is None:
        return normalized
    parsed = urlsplit(normalized)
    host = parsed.hostname or "localhost"
    port = f":{parsed.port}" if parsed.port else ""
    return urlunsplit(
        (
            parsed.scheme,
            f"{username}:runtime@{host}{port}",
            parsed.path,
            parsed.query,
            parsed.fragment,
        )
    )


@pytest.mark.asyncio
async def test_postgres_rls_blocks_orm_and_raw_vector_cross_tenant_access() -> None:
    settings = get_settings()
    admin = await asyncpg.connect(asyncpg_dsn(settings.database_url))
    runtime_role = "agriverse_test_runtime"
    org_a, org_b = uuid.uuid4(), uuid.uuid4()
    user_a, user_b = uuid.uuid4(), uuid.uuid4()
    farm_a, farm_b = uuid.uuid4(), uuid.uuid4()
    field_a, field_b = uuid.uuid4(), uuid.uuid4()
    scan_a, scan_b = uuid.uuid4(), uuid.uuid4()
    try:
        await admin.execute(f"DROP ROLE IF EXISTS {runtime_role}")
        await admin.execute(
            f"CREATE ROLE {runtime_role} LOGIN PASSWORD 'runtime' NOSUPERUSER NOBYPASSRLS"
        )
        await admin.execute(f"GRANT CONNECT ON DATABASE agriverse TO {runtime_role}")
        await admin.execute(f"GRANT USAGE ON SCHEMA public TO {runtime_role}")
        await admin.execute(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {runtime_role}"
        )
        await admin.execute(
            "INSERT INTO organization (id, name, licence_tier, is_active) "
            "VALUES ($1, 'A', 'standard', true), ($2, 'B', 'standard', true)",
            org_a,
            org_b,
        )
        await admin.execute(
            "INSERT INTO app_user "
            "(id, provider, preferred_language, failed_login_attempts, is_active) "
            "VALUES ($1, 'phone', 'en', 0, true), ($2, 'phone', 'en', 0, true)",
            user_a,
            user_b,
        )
        await admin.execute(
            "INSERT INTO farm (id, organization_id, name, owner_user_id) "
            "VALUES ($1, $2, 'Farm A', $3), ($4, $5, 'Farm B', $6)",
            farm_a,
            org_a,
            user_a,
            farm_b,
            org_b,
            user_b,
        )
        await admin.execute(
            "INSERT INTO field "
            "(id, farm_id, organization_id, name, latitude, longitude, state, district, "
            "agro_climatic_zone) VALUES "
            "($1, $2, $3, 'Field A', 12, 77, 'KA', 'A', 'zone'), "
            "($4, $5, $6, 'Field B', 13, 78, 'KA', 'B', 'zone')",
            field_a,
            farm_a,
            org_a,
            field_b,
            farm_b,
            org_b,
        )
        await admin.execute(
            "INSERT INTO scan "
            "(id, field_id, organization_id, uploaded_by, object_key, original_filename, "
            "content_type, status) VALUES "
            "($1, $2, $3, $4, 'a', 'a.jpg', 'image/jpeg', 'completed'), "
            "($5, $6, $7, $8, 'b', 'b.jpg', 'image/jpeg', 'completed')",
            scan_a,
            field_a,
            org_a,
            user_a,
            scan_b,
            field_b,
            org_b,
            user_b,
        )
        vector = "[" + ",".join(["0"] * settings.vector_dimension) + "]"
        await admin.execute(
            "INSERT INTO scan_embedding (id, scan_id, organization_id, embedding) "
            "VALUES ($1, $2, $3, $4::vector), ($5, $6, $7, $4::vector)",
            uuid.uuid4(),
            scan_a,
            org_a,
            vector,
            uuid.uuid4(),
            scan_b,
            org_b,
        )
    finally:
        await admin.close()

    runtime = await asyncpg.connect(asyncpg_dsn(settings.database_url, username=runtime_role))
    try:
        async with runtime.transaction():
            await runtime.execute("SELECT set_config('app.org_id', $1, true)", str(org_a))
            farms = await runtime.fetch("SELECT id FROM farm ORDER BY id")
            assert [row["id"] for row in farms] == [farm_a]
            nearest = await runtime.fetch(
                "SELECT scan_id FROM scan_embedding ORDER BY embedding <=> $1::vector LIMIT 10",
                vector,
            )
            assert [row["scan_id"] for row in nearest] == [scan_a]
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_redis_and_minio_round_trip() -> None:
    settings = get_settings()
    redis = Redis.from_url(settings.redis_url)
    try:
        assert await redis.ping()
    finally:
        await redis.aclose()

    await storage.ensure_bucket()
    key = f"integration/{uuid.uuid4()}.jpg"
    await storage.write_canonical_image(key, b"integration-image")
    assert await storage.read(key) == b"integration-image"
    metadata = await storage.head(key)
    assert metadata["ContentLength"] == len(b"integration-image")
    await storage.delete(key)
    with pytest.raises(ObjectNotFoundError):
        await storage.head(key)
