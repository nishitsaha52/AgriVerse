import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from agriverse.models import AuditLog
from agriverse.security import Principal


def record_audit(
    db: AsyncSession,
    principal: Principal,
    *,
    action: str,
    resource_type: str,
    resource_id: uuid.UUID | str | None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> None:
    db.add(
        AuditLog(
            organization_id=principal.organization_id,
            actor_user_id=principal.user_id,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id else None,
            before=before,
            after=after,
            request_id=request_id,
        )
    )
