import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agriverse.audit import record_audit
from agriverse.db import get_db
from agriverse.dependencies import require_permissions
from agriverse.models import Farm, FieldRecord
from agriverse.schemas import (
    FarmCreate,
    FarmRead,
    FarmUpdate,
    FieldCreate,
    FieldRead,
    FieldUpdate,
)
from agriverse.security import Principal

router = APIRouter(tags=["farms and fields"])


@router.get("/farms", response_model=list[FarmRead])
async def list_farms(
    principal: Principal = Depends(require_permissions("farm:read")),
    db: AsyncSession = Depends(get_db),
) -> list[Farm]:
    statement = select(Farm).where(
        Farm.organization_id == principal.organization_id,
        Farm.deleted_at.is_(None),
    )
    if principal.role == "farmer":
        statement = statement.where(Farm.owner_user_id == principal.user_id)
    return list((await db.scalars(statement.order_by(Farm.created_at.desc()))).all())


@router.post("/farms", response_model=FarmRead, status_code=status.HTTP_201_CREATED)
async def create_farm(
    payload: FarmCreate,
    principal: Principal = Depends(require_permissions("farm:write")),
    db: AsyncSession = Depends(get_db),
) -> Farm:
    owner_id = principal.user_id if principal.role == "farmer" else payload.owner_user_id
    farm = Farm(
        organization_id=principal.organization_id,
        name=payload.name,
        owner_user_id=owner_id,
    )
    db.add(farm)
    await db.flush()
    record_audit(
        db,
        principal,
        action="farm.created",
        resource_type="farm",
        resource_id=farm.id,
        after={"name": farm.name, "owner_user_id": str(owner_id) if owner_id else None},
    )
    await db.commit()
    await db.refresh(farm)
    return farm


async def authorize_farm(
    db: AsyncSession,
    principal: Principal,
    farm_id: uuid.UUID,
) -> Farm:
    statement = select(Farm).where(
        Farm.id == farm_id,
        Farm.organization_id == principal.organization_id,
        Farm.deleted_at.is_(None),
    )
    if principal.role == "farmer":
        statement = statement.where(Farm.owner_user_id == principal.user_id)
    farm = await db.scalar(statement)
    if farm is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Farm not found")
    return farm


@router.patch("/farms/{farm_id}", response_model=FarmRead)
async def update_farm(
    farm_id: uuid.UUID,
    payload: FarmUpdate,
    principal: Principal = Depends(require_permissions("farm:write")),
    db: AsyncSession = Depends(get_db),
) -> Farm:
    farm = await authorize_farm(db, principal, farm_id)
    before = {"name": farm.name, "owner_user_id": str(farm.owner_user_id)}
    changes = payload.model_dump(exclude_unset=True)
    if principal.role == "farmer":
        changes.pop("owner_user_id", None)
    for name, value in changes.items():
        setattr(farm, name, value)
    record_audit(
        db,
        principal,
        action="farm.updated",
        resource_type="farm",
        resource_id=farm.id,
        before=before,
        after=payload.model_dump(mode="json", exclude_unset=True),
    )
    await db.commit()
    await db.refresh(farm)
    return farm


@router.delete("/farms/{farm_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_farm(
    farm_id: uuid.UUID,
    principal: Principal = Depends(require_permissions("farm:write")),
    db: AsyncSession = Depends(get_db),
) -> None:
    farm = await authorize_farm(db, principal, farm_id)
    farm.deleted_at = datetime.now(UTC)
    record_audit(
        db,
        principal,
        action="farm.deleted",
        resource_type="farm",
        resource_id=farm.id,
        before={"name": farm.name},
    )
    await db.commit()


@router.get("/fields", response_model=list[FieldRead])
async def list_fields(
    principal: Principal = Depends(require_permissions("field:read")),
    db: AsyncSession = Depends(get_db),
) -> list[FieldRecord]:
    statement = (
        select(FieldRecord)
        .join(Farm, Farm.id == FieldRecord.farm_id)
        .where(
            FieldRecord.organization_id == principal.organization_id,
            FieldRecord.deleted_at.is_(None),
            Farm.deleted_at.is_(None),
        )
    )
    if principal.role == "farmer":
        statement = statement.where(Farm.owner_user_id == principal.user_id)
    return list((await db.scalars(statement.order_by(FieldRecord.created_at.desc()))).all())


@router.get("/fields/{field_id}", response_model=FieldRead)
async def get_field(
    field_id: uuid.UUID,
    principal: Principal = Depends(require_permissions("field:read")),
    db: AsyncSession = Depends(get_db),
) -> FieldRecord:
    statement = (
        select(FieldRecord)
        .join(Farm, Farm.id == FieldRecord.farm_id)
        .where(
            FieldRecord.id == field_id,
            FieldRecord.organization_id == principal.organization_id,
            FieldRecord.deleted_at.is_(None),
            Farm.deleted_at.is_(None),
        )
    )
    if principal.role == "farmer":
        statement = statement.where(Farm.owner_user_id == principal.user_id)
    field = await db.scalar(statement)
    if field is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Field not found")
    return field


@router.post("/fields", response_model=FieldRead, status_code=status.HTTP_201_CREATED)
async def create_field(
    payload: FieldCreate,
    principal: Principal = Depends(require_permissions("field:write")),
    db: AsyncSession = Depends(get_db),
) -> FieldRecord:
    farm_statement = select(Farm).where(
        Farm.id == payload.farm_id,
        Farm.organization_id == principal.organization_id,
        Farm.deleted_at.is_(None),
    )
    if principal.role == "farmer":
        farm_statement = farm_statement.where(Farm.owner_user_id == principal.user_id)
    farm = await db.scalar(farm_statement)
    if farm is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Farm not found")
    field = FieldRecord(
        organization_id=principal.organization_id,
        **payload.model_dump(),
    )
    db.add(field)
    await db.flush()
    record_audit(
        db,
        principal,
        action="field.created",
        resource_type="field",
        resource_id=field.id,
        after=payload.model_dump(mode="json"),
    )
    await db.commit()
    await db.refresh(field)
    return field


@router.patch("/fields/{field_id}", response_model=FieldRead)
async def update_field(
    field_id: uuid.UUID,
    payload: FieldUpdate,
    principal: Principal = Depends(require_permissions("field:write")),
    db: AsyncSession = Depends(get_db),
) -> FieldRecord:
    field = await get_field(field_id, principal, db)
    before = {
        "name": field.name,
        "current_crop": field.current_crop,
        "district": field.district,
    }
    for name, value in payload.model_dump(exclude_unset=True).items():
        setattr(field, name, value)
    record_audit(
        db,
        principal,
        action="field.updated",
        resource_type="field",
        resource_id=field.id,
        before=before,
        after=payload.model_dump(mode="json", exclude_unset=True),
    )
    await db.commit()
    await db.refresh(field)
    return field


@router.delete("/fields/{field_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_field(
    field_id: uuid.UUID,
    principal: Principal = Depends(require_permissions("field:write")),
    db: AsyncSession = Depends(get_db),
) -> None:
    field = await get_field(field_id, principal, db)
    field.deleted_at = datetime.now(UTC)
    record_audit(
        db,
        principal,
        action="field.deleted",
        resource_type="field",
        resource_id=field.id,
        before={"name": field.name},
    )
    await db.commit()
