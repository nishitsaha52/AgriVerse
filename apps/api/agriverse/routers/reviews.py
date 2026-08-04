import uuid
from datetime import UTC, datetime
from typing import cast

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agriverse.audit import record_audit
from agriverse.db import get_db
from agriverse.dependencies import require_permissions
from agriverse.models import (
    AgronomistReviewQueue,
    Diagnosis,
    ScanEmbedding,
)
from agriverse.schemas import ReviewDecision, ReviewRead
from agriverse.security import Principal
from agriverse.services.idempotency import (
    replay_idempotent_response,
    store_idempotent_response,
)

router = APIRouter(prefix="/reviews", tags=["agronomist reviews"])


@router.get("", response_model=list[ReviewRead])
async def list_reviews(
    principal: Principal = Depends(require_permissions("review:write")),
    db: AsyncSession = Depends(get_db),
) -> list[AgronomistReviewQueue]:
    return list(
        (
            await db.scalars(
                select(AgronomistReviewQueue)
                .where(
                    AgronomistReviewQueue.organization_id == principal.organization_id,
                    AgronomistReviewQueue.status.in_(["pending", "in_review"]),
                )
                .order_by(
                    AgronomistReviewQueue.priority_score.desc(),
                    AgronomistReviewQueue.created_at,
                )
            )
        ).all()
    )


@router.post("/{review_id}/decision")
async def decide_review(
    review_id: uuid.UUID,
    payload: ReviewDecision,
    idempotency_key: str = Header(min_length=8, max_length=128, alias="Idempotency-Key"),
    principal: Principal = Depends(require_permissions("review:write")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    operation = f"review.decision:{review_id}"
    replay = await replay_idempotent_response(
        db,
        organization_id=principal.organization_id,
        key=idempotency_key,
        operation=operation,
    )
    if replay is not None:
        return cast(dict[str, str], replay)
    review = await db.scalar(
        select(AgronomistReviewQueue).where(
            AgronomistReviewQueue.id == review_id,
            AgronomistReviewQueue.organization_id == principal.organization_id,
        )
    )
    if review is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found")
    if review.status == "resolved":
        return {"status": "resolved"}

    embedding = await db.scalar(
        select(ScanEmbedding).where(ScanEmbedding.scan_id == review.scan_id)
    )
    if payload.decision != "indeterminate" and embedding is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The scan has no embedding and cannot enter the confirmed corpus",
        )
    diagnosis = await db.scalar(select(Diagnosis).where(Diagnosis.scan_id == review.scan_id))
    if payload.decision in {"confirmed", "corrected"} and embedding is not None:
        embedding.confirmed_dx = payload.confirmed_diagnosis
        embedding.confirmed_by = principal.user_id
        embedding.confirmed_at = datetime.now(UTC)
        if diagnosis is not None and payload.decision == "corrected":
            response = dict(diagnosis.full_response)
            response["agronomist_correction"] = payload.confirmed_diagnosis
            diagnosis.full_response = response

    review.status = "resolved"
    review.assigned_to = principal.user_id
    review.resolved_at = datetime.now(UTC)
    record_audit(
        db,
        principal,
        action="diagnosis.reviewed",
        resource_type="scan",
        resource_id=review.scan_id,
        after=payload.model_dump(),
    )
    response_body = {"status": "resolved"}
    store_idempotent_response(
        db,
        organization_id=principal.organization_id,
        key=idempotency_key,
        operation=operation,
        status_code=status.HTTP_200_OK,
        response_body=response_body,
    )
    await db.commit()
    return response_body
