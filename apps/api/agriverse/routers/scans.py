import uuid
from typing import Literal, cast

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agriverse.audit import record_audit
from agriverse.config import get_settings
from agriverse.db import get_db
from agriverse.dependencies import enforce_ai_quota, require_permissions
from agriverse.models import (
    AgronomistReviewQueue,
    Diagnosis,
    FarmerOutcomeFeedback,
    Scan,
)
from agriverse.routers.soil import authorize_field
from agriverse.schemas import (
    DiagnosisResult,
    FeedbackCreate,
    ScanCreate,
    ScanRead,
    ScanUpload,
)
from agriverse.security import Principal
from agriverse.services.idempotency import (
    replay_idempotent_response,
    store_idempotent_response,
)
from agriverse.services.storage import ObjectNotFoundError, storage

settings = get_settings()
router = APIRouter(tags=["scans"])


def get_queue(request: Request) -> ArqRedis:
    queue = getattr(request.app.state, "queue", None)
    if queue is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Background queue unavailable",
        )
    return cast(ArqRedis, queue)


@router.post(
    "/fields/{field_id}/scans",
    response_model=ScanUpload,
    status_code=status.HTTP_201_CREATED,
)
async def create_scan(
    field_id: uuid.UUID,
    payload: ScanCreate,
    principal: Principal = Depends(require_permissions("scan:write")),
    db: AsyncSession = Depends(get_db),
) -> ScanUpload:
    await authorize_field(db, principal, field_id)
    scan_id = uuid.uuid4()
    suffix = {
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
    }[payload.content_type]
    object_key = f"org/{principal.organization_id}/scans/{scan_id}/original.{suffix}"
    scan = Scan(
        id=scan_id,
        field_id=field_id,
        organization_id=principal.organization_id,
        uploaded_by=principal.user_id,
        object_key=object_key,
        original_filename=payload.filename,
        content_type=payload.content_type,
        status="pending",
    )
    db.add(scan)
    await db.commit()
    upload_url = await storage.presign_upload(object_key, payload.content_type)
    return ScanUpload(
        scan_id=scan_id,
        upload_url=upload_url,
        object_key=object_key,
        expires_in=settings.presigned_url_seconds,
        required_headers=storage.upload_headers(payload.content_type),
    )


@router.post("/scans/{scan_id}/complete", status_code=status.HTTP_202_ACCEPTED)
async def complete_scan(
    scan_id: uuid.UUID,
    request: Request,
    idempotency_key: str = Header(min_length=8, max_length=128, alias="Idempotency-Key"),
    principal: Principal = Depends(require_permissions("scan:write")),
    quota_principal: Principal = Depends(enforce_ai_quota),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    del quota_principal
    operation = f"scan.complete:{scan_id}"
    replay = await replay_idempotent_response(
        db,
        organization_id=principal.organization_id,
        key=idempotency_key,
        operation=operation,
    )
    if replay is not None:
        return cast(dict[str, str], replay)
    statement = select(Scan).where(
        Scan.id == scan_id,
        Scan.organization_id == principal.organization_id,
    )
    if principal.role == "farmer":
        statement = statement.where(Scan.uploaded_by == principal.user_id)
    scan = await db.scalar(statement)
    if scan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scan not found")
    if scan.status not in {"pending", "processing"}:
        return {"status": scan.status}
    try:
        metadata = await storage.head(scan.object_key)
    except ObjectNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Upload is not complete"
        ) from exc
    if int(metadata.get("ContentLength", 0)) > settings.max_image_bytes:
        scan.status = "rejected"
        scan.failure_code = "image_too_large"
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Image exceeds 10 MB",
        )
    stored_type = str(metadata.get("ContentType", "")).split(";")[0]
    if stored_type != scan.content_type:
        scan.status = "rejected"
        scan.failure_code = "content_type_mismatch"
        await db.commit()
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE)
    queue = get_queue(request)
    await queue.enqueue_job(
        "process_scan",
        str(scan.id),
        str(principal.organization_id),
        principal.preferred_language,
        _job_id=f"scan:{scan.id}",
    )
    scan.status = "processing"
    response_body = {"status": "processing"}
    store_idempotent_response(
        db,
        organization_id=principal.organization_id,
        key=idempotency_key,
        operation=operation,
        status_code=status.HTTP_202_ACCEPTED,
        response_body=response_body,
    )
    await db.commit()
    return response_body


def diagnosis_to_schema(diagnosis: Diagnosis | None) -> DiagnosisResult | None:
    if diagnosis is None:
        return None
    return DiagnosisResult.model_validate(diagnosis.full_response)


@router.get("/scans/{scan_id}", response_model=ScanRead)
async def get_scan(
    scan_id: uuid.UUID,
    principal: Principal = Depends(require_permissions("field:read")),
    db: AsyncSession = Depends(get_db),
) -> ScanRead:
    statement = select(Scan).where(
        Scan.id == scan_id,
        Scan.organization_id == principal.organization_id,
    )
    if principal.role == "farmer":
        statement = statement.where(Scan.uploaded_by == principal.user_id)
    scan = await db.scalar(statement)
    if scan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scan not found")
    diagnosis = await db.scalar(select(Diagnosis).where(Diagnosis.scan_id == scan.id))
    return ScanRead(
        id=scan.id,
        field_id=scan.field_id,
        status=cast(
            Literal["pending", "processing", "completed", "rejected", "failed"],
            scan.status,
        ),
        created_at=scan.created_at,
        diagnosis=diagnosis_to_schema(diagnosis),
        failure_code=scan.failure_code,
    )


@router.post(
    "/scans/{scan_id}/feedback",
    status_code=status.HTTP_201_CREATED,
)
async def submit_feedback(
    scan_id: uuid.UUID,
    payload: FeedbackCreate,
    idempotency_key: str = Header(min_length=8, max_length=128, alias="Idempotency-Key"),
    principal: Principal = Depends(require_permissions("feedback:write")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    operation = f"scan.feedback:{scan_id}"
    replay = await replay_idempotent_response(
        db,
        organization_id=principal.organization_id,
        key=idempotency_key,
        operation=operation,
    )
    if replay is not None:
        return cast(dict[str, str], replay)
    scan = await db.scalar(
        select(Scan).where(
            Scan.id == scan_id,
            Scan.organization_id == principal.organization_id,
            Scan.uploaded_by == principal.user_id,
            Scan.status == "completed",
        )
    )
    if scan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scan not found")
    db.add(
        FarmerOutcomeFeedback(
            scan_id=scan.id,
            organization_id=principal.organization_id,
            submitted_by=principal.user_id,
            outcome=payload.outcome,
            notes=payload.notes,
        )
    )
    if payload.outcome == "failed":
        existing = await db.scalar(
            select(AgronomistReviewQueue).where(AgronomistReviewQueue.scan_id == scan.id)
        )
        if existing is None:
            db.add(
                AgronomistReviewQueue(
                    scan_id=scan.id,
                    organization_id=principal.organization_id,
                    reason="negative_feedback",
                    priority_score=90,
                )
            )
        elif existing.status == "pending":
            existing.priority_score = max(existing.priority_score, 90)
            existing.reason = "negative_feedback"
    record_audit(
        db,
        principal,
        action="scan.feedback_submitted",
        resource_type="scan",
        resource_id=scan.id,
        after=payload.model_dump(),
    )
    response_body = {"status": "recorded"}
    store_idempotent_response(
        db,
        organization_id=principal.organization_id,
        key=idempotency_key,
        operation=operation,
        status_code=status.HTTP_201_CREATED,
        response_body=response_body,
    )
    await db.commit()
    return response_body
