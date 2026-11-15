"""Provision an isolated application role using the migration/admin connection.

Credentials are generated locally and written only to the ignored root .env.
Existing roles are never reset. No existing records or database owners change.
"""

import asyncio
import re
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from agriverse.config import get_settings

ROOT_ENV = Path(__file__).resolve().parents[3] / ".env"


async def main() -> None:
    settings = get_settings()
    admin_url = settings.migration_database_url or settings.database_url
    role = "agriverse_runtime"
    env_path = ROOT_ENV
    env_text = await asyncio.to_thread(env_path.read_text, encoding="utf-8")
    admin = create_async_engine(admin_url, echo=False)
    try:
        async with admin.begin() as conn:
            exists = await conn.scalar(
                text("SELECT 1 FROM pg_roles WHERE rolname=:role"), {"role": role}
            )
            if exists:
                if make_url(settings.database_url).username == role:
                    print("Runtime role already configured; no changes made.")
                    return
                raise RuntimeError("Runtime role exists; refusing to replace its credentials")
            password = secrets.token_urlsafe(48)
            statement = await conn.scalar(
                text(
                    "SELECT format('CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                    "NOREPLICATION NOBYPASSRLS NOINHERIT PASSWORD %L', "
                    "CAST(:role AS text), CAST(:password AS text))"
                ),
                {"role": role, "password": password},
            )
            await conn.execute(text(statement))
            database = await conn.scalar(text("SELECT current_database()"))
            statement = await conn.scalar(
                text(
                    "SELECT format('GRANT CONNECT ON DATABASE %I TO %I', "
                    "CAST(:db AS text), CAST(:role AS text))"
                ),
                {"db": database, "role": role},
            )
            await conn.execute(text(statement))
            await conn.execute(text('GRANT USAGE ON SCHEMA public TO "agriverse_runtime"'))
            await conn.execute(
                text('GRANT SELECT ON TABLE public.alembic_version TO "agriverse_runtime"')
            )
            tables = list(
                (
                    await conn.execute(
                        text(
                            "SELECT tablename FROM pg_tables WHERE schemaname='public' "
                            "AND tablename <> 'alembic_version'"
                        )
                    )
                ).scalars()
            )
            for table in tables:
                statement = await conn.scalar(
                    text(
                        "SELECT format('GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "
                        "public.%I TO %I', CAST(:table AS text), CAST(:role AS text))"
                    ),
                    {"table": table, "role": role},
                )
                await conn.execute(text(statement))
            await conn.execute(
                text('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "agriverse_runtime"')
            )
            await conn.execute(
                text(
                    "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, "
                    'DELETE ON TABLES TO "agriverse_runtime"'
                )
            )
            await conn.execute(
                text(
                    "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT "
                    'ON SEQUENCES TO "agriverse_runtime"'
                )
            )
        runtime_url = make_url(settings.database_url).set(username=role, password=password)
        runtime = create_async_engine(runtime_url, echo=False)
        try:
            async with runtime.connect() as conn:
                await conn.execute(text("SET TRANSACTION READ ONLY"))
                privileges = (
                    (
                        await conn.execute(
                            text(
                                "SELECT r.rolsuper, r.rolbypassrls, "
                                "has_schema_privilege(current_user,'public','CREATE') "
                                "AS schema_create "
                                "FROM pg_roles r WHERE rolname=current_user"
                            )
                        )
                    )
                    .mappings()
                    .one()
                )
                assert not any(privileges.values())
                assert await conn.scalar(text("SELECT count(*) FROM membership")) == 0
                org = await conn.scalar(text("SELECT id FROM organization LIMIT 1"))
                if org:
                    await conn.execute(
                        text("SELECT set_config('app.org_id',:org,true)"), {"org": str(org)}
                    )
                    visible = await conn.scalar(text("SELECT count(*) FROM membership"))
                    await conn.execute(
                        text(
                            "SELECT set_config('app.org_id',"
                            "'00000000-0000-0000-0000-000000000000',true)"
                        )
                    )
                    assert await conn.scalar(text("SELECT count(*) FROM membership")) == 0
                    print(f"Tenant-context membership visibility: {visible}; other/no tenant: 0.")
        finally:
            await runtime.dispose()
        updates = {
            "DATABASE_URL": runtime_url.render_as_string(hide_password=False),
            "MIGRATION_DATABASE_URL": admin_url,
        }
        for key, value in updates.items():
            pattern = rf"(?m)^{key}=.*$"
            env_text = (
                re.sub(pattern, lambda m, k=key, v=value: f"{k}={v}", env_text)
                if re.search(pattern, env_text)
                else env_text + f"\n{key}={value}\n"
            )
        await asyncio.to_thread(env_path.write_text, env_text, encoding="utf-8")
        print(
            "Configured least-privilege runtime role; separate migration URL preserved privately."
        )
    finally:
        await admin.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        # Database exceptions can contain SQL/password parameters. Never print them.
        sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
        print(
            f"Runtime role provisioning failed ({type(exc).__name__}, SQLSTATE={sqlstate}); "
            "credentials omitted."
        )
        raise SystemExit(1) from None
