import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agriverse.models import IdempotencyRecord


async def replay_idempotent_response(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    key: str,
    operation: str,
) -> dict[str, Any] | None:
    record = await db.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.organization_id == organization_id,
            IdempotencyRecord.key == key,
            IdempotencyRecord.operation == operation,
            IdempotencyRecord.expires_at > datetime.now(UTC),
        )
    )
    return None if record is None else dict(record.response_body)


def store_idempotent_response(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    key: str,
    operation: str,
    status_code: int,
    response_body: dict[str, Any],
) -> None:
    db.add(
        IdempotencyRecord(
            organization_id=organization_id,
            key=key,
            operation=operation,
            response_status=status_code,
            response_body=response_body,
            expires_at=datetime.now(UTC) + timedelta(hours=24),
        )
    )
