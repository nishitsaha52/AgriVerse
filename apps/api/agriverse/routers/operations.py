from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agriverse.audit import record_audit
from agriverse.db import get_db
from agriverse.dependencies import require_permissions
from agriverse.models import (
    AgentConversation,
    AgentMessage,
    AuditLog,
    Farm,
    FarmerOutcomeFeedback,
    FieldRecord,
    Membership,
    Organization,
    RefreshSession,
    Scan,
    SoilTest,
    UsageRecord,
    User,
)
from agriverse.schemas import (
    AuditRead,
    MembershipRead,
    OrganizationRead,
    UsageRead,
)
from agriverse.security import Principal
from agriverse.services.storage import storage

router = APIRouter(tags=["organization operations"])


@router.get("/organization", response_model=OrganizationRead)
async def get_organization(
    principal: Principal = Depends(require_permissions("field:read")),
    db: AsyncSession = Depends(get_db),
) -> Organization:
    organization = await db.get(Organization, principal.organization_id)
    if organization is None:
        raise RuntimeError("Authenticated organization no longer exists")
    return organization


@router.get("/organization/memberships", response_model=list[MembershipRead])
async def list_memberships(
    principal: Principal = Depends(require_permissions("farmer:onboard")),
    db: AsyncSession = Depends(get_db),
) -> list[Membership]:
    return list(
        (
            await db.scalars(
                select(Membership)
                .where(Membership.organization_id == principal.organization_id)
                .order_by(Membership.created_at.desc())
            )
        ).all()
    )


@router.get("/usage", response_model=list[UsageRead])
async def list_usage(
    principal: Principal = Depends(require_permissions("audit:read")),
    db: AsyncSession = Depends(get_db),
) -> list[UsageRecord]:
    return list(
        (
            await db.scalars(
                select(UsageRecord)
                .where(UsageRecord.organization_id == principal.organization_id)
                .order_by(UsageRecord.created_at.desc())
                .limit(500)
            )
        ).all()
    )


@router.get("/audit", response_model=list[AuditRead])
async def list_audit(
    principal: Principal = Depends(require_permissions("audit:read")),
    db: AsyncSession = Depends(get_db),
) -> list[AuditLog]:
    return list(
        (
            await db.scalars(
                select(AuditLog)
                .where(AuditLog.organization_id == principal.organization_id)
                .order_by(AuditLog.created_at.desc())
                .limit(500)
            )
        ).all()
    )


async def _rows_as_dicts(db: AsyncSession, statement: Any) -> list[dict[str, Any]]:
    rows = (await db.execute(statement)).mappings().all()
    return [
        {
            key: value.isoformat() if isinstance(value, datetime) else value
            for key, value in row.items()
        }
        for row in rows
    ]


@router.get("/privacy/export")
async def export_my_data(
    principal: Principal = Depends(require_permissions("field:read")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    user_columns = select(
        User.id,
        User.phone_e164,
        User.preferred_language,
        User.created_at,
    ).where(User.id == principal.user_id)
    farms = select(*Farm.__table__.c).where(
        Farm.organization_id == principal.organization_id,
        Farm.owner_user_id == principal.user_id,
    )
    fields = (
        select(*FieldRecord.__table__.c)
        .join(Farm, Farm.id == FieldRecord.farm_id)
        .where(
            FieldRecord.organization_id == principal.organization_id,
            Farm.owner_user_id == principal.user_id,
        )
    )
    soil_tests = (
        select(*SoilTest.__table__.c)
        .join(FieldRecord, FieldRecord.id == SoilTest.field_id)
        .join(Farm, Farm.id == FieldRecord.farm_id)
        .where(
            SoilTest.organization_id == principal.organization_id,
            Farm.owner_user_id == principal.user_id,
        )
    )
    scans = select(*Scan.__table__.c).where(
        Scan.organization_id == principal.organization_id,
        Scan.uploaded_by == principal.user_id,
    )
    feedback = select(*FarmerOutcomeFeedback.__table__.c).where(
        FarmerOutcomeFeedback.organization_id == principal.organization_id,
        FarmerOutcomeFeedback.submitted_by == principal.user_id,
    )
    conversations = select(*AgentConversation.__table__.c).where(
        AgentConversation.organization_id == principal.organization_id,
        AgentConversation.user_id == principal.user_id,
    )
    conversation_ids = select(AgentConversation.id).where(
        AgentConversation.organization_id == principal.organization_id,
        AgentConversation.user_id == principal.user_id,
    )
    messages = select(*AgentMessage.__table__.c).where(
        AgentMessage.organization_id == principal.organization_id,
        AgentMessage.conversation_id.in_(conversation_ids),
    )
    return {
        "exported_at": datetime.now(UTC).isoformat(),
        "organization_id": str(principal.organization_id),
        "account": await _rows_as_dicts(db, user_columns),
        "farms": await _rows_as_dicts(db, farms),
        "fields": await _rows_as_dicts(db, fields),
        "soil_tests": await _rows_as_dicts(db, soil_tests),
        "scans": await _rows_as_dicts(db, scans),
        "feedback": await _rows_as_dicts(db, feedback),
        "conversations": await _rows_as_dicts(db, conversations),
        "messages": await _rows_as_dicts(db, messages),
    }


@router.delete("/privacy/account", status_code=status.HTTP_202_ACCEPTED)
async def erase_my_account(
    principal: Principal = Depends(require_permissions("field:read")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    user = await db.get(User, principal.user_id)
    scans = list(
        (
            await db.scalars(
                select(Scan).where(
                    Scan.organization_id == principal.organization_id,
                    Scan.uploaded_by == principal.user_id,
                )
            )
        ).all()
    )
    for scan in scans:
        await storage.delete(scan.object_key)
        canonical_key = scan.object_key.rsplit("/", 1)[0] + "/canonical.jpg"
        await storage.delete(canonical_key)
        scan.original_filename = "erased"
        scan.object_key = f"erased/{scan.id}"
    if user is not None:
        user.phone_e164 = None
        user.oauth_subject = None
        user.pin_hash = None
        user.preferred_language = "en"
        user.is_active = False
    sessions = list(
        (
            await db.scalars(
                select(RefreshSession).where(
                    RefreshSession.organization_id == principal.organization_id,
                    RefreshSession.user_id == principal.user_id,
                    RefreshSession.revoked_at.is_(None),
                )
            )
        ).all()
    )
    now = datetime.now(UTC)
    for session in sessions:
        session.revoked_at = now
    record_audit(
        db,
        principal,
        action="privacy.account_erased",
        resource_type="user",
        resource_id=principal.user_id,
        after={"objects_deleted": len(scans), "sessions_revoked": len(sessions)},
    )
    await db.commit()
    return {"status": "erased"}
