import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agriverse.audit import record_audit
from agriverse.db import get_db
from agriverse.dependencies import require_permissions
from agriverse.models import CropRecommendation, Farm, FieldRecord, SoilTest
from agriverse.schemas import SoilTestCreate, SoilTestRead
from agriverse.security import Principal
from agriverse.services.agronomy import (
    ALGORITHM_VERSION,
    FERTILITY_SOURCES,
    compute_fertility_index,
    rank_crop_suitability,
)

router = APIRouter(tags=["soil and crop recommendations"])


async def authorize_field(
    db: AsyncSession, principal: Principal, field_id: uuid.UUID
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


@router.post(
    "/fields/{field_id}/soil-tests",
    response_model=SoilTestRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_soil_test(
    field_id: uuid.UUID,
    payload: SoilTestCreate,
    principal: Principal = Depends(require_permissions("soil:write")),
    db: AsyncSession = Depends(get_db),
) -> SoilTestRead:
    await authorize_field(db, principal, field_id)
    fertility_index = compute_fertility_index(payload)
    ranked_crops = rank_crop_suitability(payload)
    soil_test = SoilTest(
        field_id=field_id,
        organization_id=principal.organization_id,
        fertility_index=fertility_index,
        algorithm_version=ALGORITHM_VERSION,
        **payload.model_dump(),
    )
    db.add(soil_test)
    await db.flush()
    recommendation = CropRecommendation(
        field_id=field_id,
        organization_id=principal.organization_id,
        soil_test_id=soil_test.id,
        ranked_crops=[crop.model_dump() for crop in ranked_crops],
        algorithm_version=ALGORITHM_VERSION,
    )
    db.add(recommendation)
    record_audit(
        db,
        principal,
        action="soil_test.created",
        resource_type="soil_test",
        resource_id=soil_test.id,
        after={
            "fertility_index": str(fertility_index),
            "algorithm_version": ALGORITHM_VERSION,
        },
    )
    await db.commit()
    await db.refresh(soil_test)
    response = SoilTestRead.model_validate(soil_test)
    return response.model_copy(
        update={
            "ranked_crops": ranked_crops,
            "algorithm_sources": FERTILITY_SOURCES,
        }
    )


@router.get("/fields/{field_id}/soil-tests/latest", response_model=SoilTestRead)
async def latest_soil_test(
    field_id: uuid.UUID,
    principal: Principal = Depends(require_permissions("field:read")),
    db: AsyncSession = Depends(get_db),
) -> SoilTestRead:
    await authorize_field(db, principal, field_id)
    soil_test = await db.scalar(
        select(SoilTest)
        .where(
            SoilTest.field_id == field_id,
            SoilTest.organization_id == principal.organization_id,
        )
        .order_by(SoilTest.created_at.desc())
        .limit(1)
    )
    if soil_test is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No soil test found")
    recommendation = await db.scalar(
        select(CropRecommendation).where(CropRecommendation.soil_test_id == soil_test.id).limit(1)
    )
    ranked = recommendation.ranked_crops if recommendation else []
    return SoilTestRead.model_validate(soil_test).model_copy(
        update={
            "ranked_crops": ranked,
            "algorithm_sources": FERTILITY_SOURCES,
        }
    )
