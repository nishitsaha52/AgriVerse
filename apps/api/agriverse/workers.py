import hashlib
import re
import uuid
import warnings
from io import BytesIO
from typing import Any

from arq.connections import RedisSettings
from PIL import Image, UnidentifiedImageError
from sqlalchemy import select

from agriverse.config import get_settings
from agriverse.db import SessionFactory
from agriverse.dependencies import set_tenant_context
from agriverse.models import (
    AgronomistReviewQueue,
    AuditLog,
    Diagnosis,
    FieldRecord,
    Scan,
    ScanEmbedding,
    SoilTest,
    UsageRecord,
)
from agriverse.schemas import DiagnosisResult
from agriverse.services.ai import (
    PROMPT_VERSION,
    FieldContext,
    RetrievedContext,
    vision_provider,
)
from agriverse.services.retrieval import (
    StoredEmbeddings,
    citations_from_document_rows,
    embedding_service,
    search_documents,
    search_similar_scans,
)
from agriverse.services.storage import storage

settings = get_settings()
Image.MAX_IMAGE_PIXELS = settings.max_image_pixels
DOSAGE_PATTERN = re.compile(
    r"\b(\d+(?:\.\d+)?\s*(?:ml|l|g|kg)\s*(?:/|per)\s*(?:l|litre|ha|acre)|"
    r"dose|dosage|pre-harvest|product)\b",
    re.IGNORECASE,
)


class InvalidImageError(Exception):
    pass


def normalize_image(raw: bytes) -> bytes:
    if len(raw) > settings.max_image_bytes:
        raise InvalidImageError("image_too_large")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw)) as image:
                image.load()
                if image.format not in {"JPEG", "PNG", "WEBP"}:
                    raise InvalidImageError("unsupported_image_type")
                if image.width * image.height > settings.max_image_pixels:
                    raise InvalidImageError("pixel_limit_exceeded")
                normalized = image.convert("RGB")
                normalized.thumbnail((1568, 1568), Image.Resampling.LANCZOS)
                output = BytesIO()
                normalized.save(output, format="JPEG", quality=90, optimize=True)
                return output.getvalue()
    except (
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        OSError,
    ) as exc:
        raise InvalidImageError("invalid_image") from exc


def apply_citation_safety(result: DiagnosisResult, retrieved: RetrievedContext) -> DiagnosisResult:
    allowed = {citation.chunk_id: citation for citation in retrieved.citations}
    citations = [
        allowed[citation.chunk_id]
        for citation in result.citations
        if citation.chunk_id is not None and citation.chunk_id in allowed
    ]
    has_tier_one = any(citation.tier == 1 for citation in citations)
    actions = result.immediate_actions
    requires_expert = result.requires_expert
    if not has_tier_one and any(DOSAGE_PATTERN.search(action) for action in actions):
        actions = [action for action in actions if DOSAGE_PATTERN.search(action) is None]
        actions.append(
            "No verified regulatory label was retrieved. Confirm any chemical treatment "
            "with a local agronomist before application."
        )
        requires_expert = True
    return result.model_copy(
        update={
            "citations": citations,
            "immediate_actions": actions,
            "requires_expert": requires_expert,
        }
    )


async def _copy_cached_diagnosis(
    db: Any,
    scan: Scan,
) -> Diagnosis | None:
    cached = await db.scalar(
        select(Diagnosis)
        .join(Scan, Scan.id == Diagnosis.scan_id)
        .where(
            Scan.organization_id == scan.organization_id,
            Scan.sha256 == scan.sha256,
            Scan.id != scan.id,
            Scan.status.in_(["completed", "rejected"]),
        )
        .order_by(Diagnosis.created_at.desc())
        .limit(1)
    )
    if cached is None:
        return None
    duplicate = Diagnosis(
        scan_id=scan.id,
        organization_id=scan.organization_id,
        image_is_diagnosable=cached.image_is_diagnosable,
        rejection_reason=cached.rejection_reason,
        primary_condition=cached.primary_condition,
        differential=cached.differential,
        immediate_actions=cached.immediate_actions,
        citations=cached.citations,
        requires_expert=cached.requires_expert,
        provider="sha256-cache",
        model_id=cached.model_id,
        prompt_version=cached.prompt_version,
        token_usage={},
        full_response=cached.full_response,
    )
    db.add(duplicate)
    scan.status = "completed" if cached.image_is_diagnosable else "rejected"
    return duplicate


async def process_scan(
    ctx: dict[str, Any],
    scan_id: str,
    organization_id: str,
    language: str = "en",
) -> None:
    del ctx
    scan_uuid = uuid.UUID(scan_id)
    org_uuid = uuid.UUID(organization_id)
    async with SessionFactory() as db:
        await set_tenant_context(db, org_uuid)
        scan = await db.scalar(
            select(Scan).where(Scan.id == scan_uuid, Scan.organization_id == org_uuid)
        )
        if scan is None or scan.status not in {"pending", "processing"}:
            return
        scan.status = "processing"
        await db.commit()
        await set_tenant_context(db, org_uuid)

        try:
            raw = await storage.read(scan.object_key)
            canonical = normalize_image(raw)
            scan.sha256 = hashlib.sha256(canonical).hexdigest()
            normalized_key = f"org/{org_uuid}/scans/{scan.id}/normalized.jpg"
            await storage.write_canonical_image(normalized_key, canonical)
            scan.object_key = normalized_key
            scan.content_type = "image/jpeg"

            if await _copy_cached_diagnosis(db, scan) is not None:
                await db.commit()
                return

            gate = await vision_provider.gate(canonical)
            db.add(
                AuditLog(
                    organization_id=org_uuid,
                    actor_user_id=scan.uploaded_by,
                    action="ai.image_gate_called",
                    resource_type="scan",
                    resource_id=str(scan.id),
                    after={
                        "provider": gate.metadata.get("provider", "unknown"),
                        "model": gate.metadata.get("model", "unknown"),
                        "prompt_version": PROMPT_VERSION,
                    },
                )
            )
            if not gate.is_plant_image or not gate.is_diagnosable:
                result = DiagnosisResult(
                    image_is_diagnosable=False,
                    rejection_reason=gate.rejection_reason or "Please retake a clear plant photo.",
                )
                db.add(
                    Diagnosis(
                        scan_id=scan.id,
                        organization_id=org_uuid,
                        image_is_diagnosable=False,
                        rejection_reason=result.rejection_reason,
                        primary_condition=None,
                        differential=[],
                        immediate_actions=[],
                        citations=[],
                        requires_expert=False,
                        provider=str(gate.metadata.get("provider", "unknown")),
                        model_id=str(gate.metadata.get("model", "unknown")),
                        prompt_version=PROMPT_VERSION,
                        token_usage={},
                        full_response=result.model_dump(mode="json"),
                    )
                )
                scan.status = "rejected"
                await db.commit()
                return

            field = await db.get(FieldRecord, scan.field_id)
            if field is None:
                raise RuntimeError("field_not_found")
            soil = await db.scalar(
                select(SoilTest)
                .where(SoilTest.field_id == field.id)
                .order_by(SoilTest.created_at.desc())
                .limit(1)
            )

            embedding: StoredEmbeddings | None = None
            similar_cases: list[dict[str, Any]] = []
            document_rows: list[dict[str, Any]] = []
            try:
                embedding = await embedding_service.embed_image(canonical)
                similar_cases = await search_similar_scans(
                    db,
                    organization_id=org_uuid,
                    embedding=embedding.preferred,
                )
                query = (
                    f"{field.current_crop or 'crop'} plant diagnosis in "
                    f"{field.agro_climatic_zone}, {field.state}"
                )
                query_embedding = (
                    await embedding_service.embed_texts([query], input_type="query")
                )[0]
                document_rows = await search_documents(
                    db,
                    query_embedding=query_embedding,
                    agro_climatic_zone=field.agro_climatic_zone,
                    query=query,
                )
            except Exception:
                # Diagnosis remains available in degraded mode; it must be reviewed.
                embedding = None

            retrieved = RetrievedContext(
                similar_cases=similar_cases,
                citations=citations_from_document_rows(document_rows),
            )
            context = FieldContext(
                field_id=field.id,
                crop=field.current_crop,
                state=field.state,
                district=field.district,
                agro_climatic_zone=field.agro_climatic_zone,
                latest_soil_summary=(
                    f"fertility_index={soil.fertility_index}, algorithm={soil.algorithm_version}"
                    if soil
                    else None
                ),
            )
            result, metadata = await vision_provider.diagnose(
                canonical,
                context,
                retrieved,
                language,
            )
            result = apply_citation_safety(result, retrieved)
            if embedding is None:
                result = result.model_copy(update={"requires_expert": True})
            db.add(
                Diagnosis(
                    scan_id=scan.id,
                    organization_id=org_uuid,
                    image_is_diagnosable=result.image_is_diagnosable,
                    rejection_reason=result.rejection_reason,
                    primary_condition=(
                        result.primary.model_dump(mode="json") if result.primary else None
                    ),
                    differential=[
                        alternative.model_dump(mode="json") for alternative in result.differential
                    ],
                    immediate_actions=result.immediate_actions,
                    citations=[citation.model_dump(mode="json") for citation in result.citations],
                    requires_expert=result.requires_expert,
                    provider=str(metadata.get("provider", "unknown")),
                    model_id=str(metadata.get("model", settings.openai_vision_model)),
                    prompt_version=PROMPT_VERSION,
                    token_usage=metadata.get("usage", {}),
                    full_response=result.model_dump(mode="json"),
                )
            )
            if embedding is not None:
                db.add(
                    ScanEmbedding(
                        scan_id=scan.id,
                        organization_id=org_uuid,
                        embedding_text=embedding.text,
                        **embedding.columns(),
                    )
                )
            primary_label = result.primary.condition.casefold() if result.primary else None
            neighbour_labels = {
                str(case.get("confirmed_dx", "")).casefold()
                for case in similar_cases
                if case.get("confirmed_dx")
            }
            neighbour_disagreement = bool(
                primary_label and neighbour_labels and primary_label not in neighbour_labels
            )
            tier_one_dosage = any(citation.tier == 1 for citation in result.citations) and any(
                DOSAGE_PATTERN.search(action) for action in result.immediate_actions
            )
            low_confidence = bool(
                result.requires_expert
                or (result.primary is not None and result.primary.confidence == "low")
            )
            review_reason: str | None = None
            review_priority = 0
            if low_confidence:
                review_reason, review_priority = "low_confidence", 100
            elif neighbour_disagreement:
                review_reason, review_priority = "neighbour_disagreement", 95
            elif tier_one_dosage:
                review_reason, review_priority = "tier_one_dosage", 90
            elif not similar_cases:
                review_reason, review_priority = "no_neighbours", 70
            if review_reason:
                db.add(
                    AgronomistReviewQueue(
                        scan_id=scan.id,
                        organization_id=org_uuid,
                        reason=review_reason,
                        priority_score=review_priority,
                    )
                )
            usage = metadata.get("usage", {})
            db.add(
                UsageRecord(
                    organization_id=org_uuid,
                    user_id=scan.uploaded_by,
                    call_type="scan_diagnosis",
                    tokens_used=int(usage.get("total_tokens", 0)),
                    cost_usd=0,
                )
            )
            db.add(
                AuditLog(
                    organization_id=org_uuid,
                    actor_user_id=scan.uploaded_by,
                    action="ai.scan_diagnosis_called",
                    resource_type="scan",
                    resource_id=str(scan.id),
                    after={
                        "provider": metadata.get("provider", "unknown"),
                        "model": metadata.get("model", settings.openai_vision_model),
                        "response_id": metadata.get("response_id"),
                        "prompt_version": PROMPT_VERSION,
                        "usage": usage,
                    },
                )
            )
            scan.status = "completed"
            await db.commit()
        except InvalidImageError as exc:
            scan.status = "rejected"
            scan.failure_code = str(exc)
            await db.commit()
        except Exception as exc:
            scan.status = "failed"
            scan.failure_code = type(exc).__name__
            await db.commit()
            raise


class WorkerSettings:
    functions = [process_scan]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    job_timeout = 300
    max_jobs = 10
    keep_result = 3600
