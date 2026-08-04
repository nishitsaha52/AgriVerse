import uuid
from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from agriverse.db import get_db
from agriverse.models import Membership, User
from agriverse.security import Principal, decode_token
from agriverse.services.rate_limit import rate_limiter

bearer = HTTPBearer(auto_error=True)

ROLE_PERMISSIONS: dict[str, set[str]] = {
    "farmer": {
        "farm:read",
        "farm:write",
        "field:read",
        "field:write",
        "soil:write",
        "scan:write",
        "feedback:write",
        "agent:use",
    },
    "field_agent": {
        "farm:read",
        "farm:write",
        "field:read",
        "field:write",
        "soil:write",
        "scan:write",
        "feedback:write",
        "farmer:onboard",
        "agent:use",
    },
    "agronomist": {
        "farm:read",
        "field:read",
        "scan:read",
        "review:write",
        "document:read",
        "agent:use",
    },
    "org_admin": {"*"},
    "support": {"farm:read", "field:read", "scan:read", "audit:read"},
    "super_admin": {"*"},
}


async def set_tenant_context(db: AsyncSession, organization_id: uuid.UUID) -> None:
    await db.execute(
        text("SELECT set_config('app.org_id', :org_id, true)"),
        {"org_id": str(organization_id)},
    )


async def get_current_principal(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> Principal:
    payload = decode_token(credentials.credentials, "access")
    try:
        user_id = uuid.UUID(payload["sub"])
        organization_id = uuid.UUID(payload["org"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        ) from exc

    await set_tenant_context(db, organization_id)
    result = await db.execute(
        select(User, Membership)
        .join(Membership, Membership.user_id == User.id)
        .where(
            User.id == user_id,
            User.is_active.is_(True),
            Membership.organization_id == organization_id,
        )
    )
    row = result.first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account unavailable")
    user, membership = row
    if membership.role != payload.get("role"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Role has changed")
    return Principal(
        user_id=user.id,
        organization_id=organization_id,
        role=membership.role,
        preferred_language=user.preferred_language,
    )


Dependency = Callable[..., Coroutine[Any, Any, Principal]]


def require_permissions(*required: str) -> Dependency:
    async def dependency(
        principal: Principal = Depends(get_current_principal),
    ) -> Principal:
        granted = ROLE_PERMISSIONS.get(principal.role, set())
        if "*" not in granted and not set(required).issubset(granted):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")
        return principal

    return dependency


async def enforce_ai_quota(
    principal: Principal = Depends(get_current_principal),
) -> Principal:
    await rate_limiter.enforce_ai_quota(principal)
    return principal
