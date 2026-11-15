import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from agriverse.config import Settings
from agriverse.models import (
    AgronomistReviewQueue,
    Diagnosis,
    Farm,
    FieldRecord,
    Scan,
    ScanEmbedding,
    SoilTest,
)
from agriverse.routers import documents, farms, reviews, scans, soil, weather
from agriverse.schemas import (
    DocumentIngest,
    DocumentSectionInput,
    FarmCreate,
    FarmUpdate,
    FeedbackCreate,
    FieldCreate,
    FieldUpdate,
    ReviewDecision,
    ScanCreate,
    SoilTestCreate,
)
from agriverse.security import Principal
from agriverse.services import storage as storage_module
from agriverse.services.retrieval import EmbeddedText, StoredEmbeddings
from tests.fakes import FakeSession

NOW = datetime.now(UTC)


def actor(role: str = "farmer") -> Principal:
    return Principal(uuid.uuid4(), uuid.uuid4(), role, "en")


def farm_record(principal: Principal) -> Farm:
    return Farm(
        id=uuid.uuid4(),
        organization_id=principal.organization_id,
        name="North farm",
        owner_user_id=principal.user_id,
        created_at=NOW,
    )


def field_record(principal: Principal, farm: Farm) -> FieldRecord:
    return FieldRecord(
        id=uuid.uuid4(),
        farm_id=farm.id,
        organization_id=principal.organization_id,
        name="Paddy east",
        latitude=Decimal("12.3"),
        longitude=Decimal("77.4"),
        state="Karnataka",
        district="Mysuru",
        agro_climatic_zone="Southern Dry Zone",
        current_crop="rice",
        created_at=NOW,
    )


def field_payload(farm: Farm) -> FieldCreate:
    return FieldCreate(
        farm_id=farm.id,
        name="Paddy east",
        latitude=Decimal("12.3"),
        longitude=Decimal("77.4"),
        state="Karnataka",
        district="Mysuru",
        agro_climatic_zone="Southern Dry Zone",
        current_crop="rice",
    )


def soil_payload() -> SoilTestCreate:
    return SoilTestCreate(
        n=350,
        p=32,
        k=210,
        ph=Decimal("6.5"),
        ec=Decimal("0.7"),
        oc=Decimal("0.9"),
        s=14,
        zn=Decimal("0.8"),
        fe=6,
        cu=Decimal("0.4"),
        mn=3,
        b=Decimal("0.7"),
    )


@pytest.mark.asyncio
async def test_farm_and_field_crud_records_audit() -> None:
    principal = actor()
    existing_farm = farm_record(principal)
    existing_field = field_record(principal, existing_farm)

    listed = await farms.list_farms(principal, FakeSession(scalar_result_values=[[existing_farm]]))
    assert listed == [existing_farm]

    create_db = FakeSession()
    created = await farms.create_farm(FarmCreate(name="Created"), principal, create_db)
    assert created.name == "Created"
    assert created.owner_user_id == principal.user_id
    assert create_db.commits == 1

    assert (
        await farms.authorize_farm(
            FakeSession(scalar_values=[existing_farm]),
            principal,
            existing_farm.id,
        )
        == existing_farm
    )
    with pytest.raises(HTTPException):
        await farms.authorize_farm(FakeSession(scalar_values=[None]), principal, uuid.uuid4())

    updated = await farms.update_farm(
        existing_farm.id,
        FarmUpdate(name="Updated", owner_user_id=uuid.uuid4()),
        principal,
        FakeSession(scalar_values=[existing_farm]),
    )
    assert updated.name == "Updated"
    assert updated.owner_user_id == principal.user_id

    await farms.delete_farm(
        existing_farm.id,
        principal,
        FakeSession(scalar_values=[existing_farm]),
    )
    assert existing_farm.deleted_at is not None

    fields = await farms.list_fields(
        principal,
        FakeSession(scalar_result_values=[[existing_field]]),
    )
    assert fields == [existing_field]
    assert (
        await farms.get_field(
            existing_field.id,
            principal,
            FakeSession(scalar_values=[existing_field]),
        )
        == existing_field
    )
    with pytest.raises(HTTPException):
        await farms.get_field(uuid.uuid4(), principal, FakeSession(scalar_values=[None]))

    field_db = FakeSession(scalar_values=[existing_farm])
    new_field = await farms.create_field(field_payload(existing_farm), principal, field_db)
    assert new_field.farm_id == existing_farm.id
    updated_field = await farms.update_field(
        existing_field.id,
        FieldUpdate(current_crop="tomato", district="Mandya"),
        principal,
        FakeSession(scalar_values=[existing_field]),
    )
    assert updated_field.current_crop == "tomato"
    await farms.delete_field(
        existing_field.id,
        principal,
        FakeSession(scalar_values=[existing_field]),
    )
    assert existing_field.deleted_at is not None


@pytest.mark.asyncio
async def test_soil_history_and_weather_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    principal = actor()
    farm = farm_record(principal)
    field = field_record(principal, farm)
    create_db = FakeSession(scalar_values=[field])
    created = await soil.create_soil_test(field.id, soil_payload(), principal, create_db)
    assert created.fertility_index > 0
    assert len(created.ranked_crops) == 3

    stored = SoilTest(
        id=uuid.uuid4(),
        field_id=field.id,
        organization_id=principal.organization_id,
        fertility_index=Decimal("72"),
        algorithm_version="v1",
        created_at=NOW,
        **soil_payload().model_dump(),
    )
    recommendation = SimpleNamespace(
        ranked_crops=[{"crop": "rice", "score": 88, "reasons": ["Suitable pH"]}]
    )
    latest = await soil.latest_soil_test(
        field.id,
        principal,
        FakeSession(scalar_values=[field, stored, recommendation]),
    )
    assert latest.ranked_crops[0]["crop"] == "rice"

    forecast = SimpleNamespace(
        source="open-meteo",
        fetched_at=NOW,
        current=SimpleNamespace(),
        alerts=[],
        model_dump=lambda **kwargs: {"source": "open-meteo"},
    )
    monkeypatch.setattr(weather.weather_service, "get_current", AsyncMock(return_value=forecast))
    weather_db = FakeSession(scalar_values=[field])
    assert (await weather.field_weather(field.id, principal, weather_db)).source == "open-meteo"
    assert weather_db.commits == 1


@pytest.mark.asyncio
async def test_scan_create_complete_read_and_feedback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(storage_module, "settings", Settings(_env_file=None))
    principal = actor()
    farm = farm_record(principal)
    field = field_record(principal, farm)
    monkeypatch.setattr(
        scans.storage,
        "presign_upload",
        AsyncMock(return_value="https://objects.example/upload"),
    )
    create_db = FakeSession(scalar_values=[field])
    upload = await scans.create_scan(
        field.id,
        ScanCreate(filename="leaf.jpg", content_type="image/jpeg"),
        principal,
        create_db,
    )
    assert upload.upload_url.startswith("https://")
    assert upload.required_headers["x-amz-server-side-encryption"] == "AES256"

    scan = Scan(
        id=uuid.uuid4(),
        field_id=field.id,
        organization_id=principal.organization_id,
        uploaded_by=principal.user_id,
        object_key="org/o/scan/original.jpg",
        original_filename="leaf.jpg",
        content_type="image/jpeg",
        status="pending",
        created_at=NOW,
    )
    monkeypatch.setattr(
        scans.storage,
        "head",
        AsyncMock(return_value={"ContentLength": 100, "ContentType": "image/jpeg"}),
    )
    queue = SimpleNamespace(enqueue_job=AsyncMock())
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(queue=queue)))
    complete_db = FakeSession(scalar_values=[None, scan])
    result = await scans.complete_scan(
        scan.id,
        request,
        "complete-key",
        principal,
        principal,
        complete_db,
    )
    assert result == {"status": "processing"}
    queue.enqueue_job.assert_awaited_once()

    diagnosis_result = {
        "image_is_diagnosable": True,
        "primary": {
            "condition": "rust",
            "category": "disease",
            "confidence": "moderate",
            "visual_evidence": "orange spots",
        },
        "differential": [],
        "immediate_actions": [],
        "citations": [],
        "requires_expert": False,
    }
    diagnosis = Diagnosis(
        scan_id=scan.id,
        organization_id=principal.organization_id,
        image_is_diagnosable=True,
        provider="openai-compatible",
        model_id="vision",
        prompt_version="v1",
        token_usage={},
        full_response=diagnosis_result,
    )
    scan.status = "completed"
    read = await scans.get_scan(
        scan.id,
        principal,
        FakeSession(scalar_values=[scan, diagnosis]),
    )
    assert read.diagnosis and read.diagnosis.primary

    feedback_db = FakeSession(scalar_values=[None, scan, None])
    response = await scans.submit_feedback(
        scan.id,
        FeedbackCreate(outcome="failed", notes="No improvement"),
        "feedback-key",
        principal,
        feedback_db,
    )
    assert response == {"status": "recorded"}
    assert any(isinstance(value, AgronomistReviewQueue) for value in feedback_db.added)


@pytest.mark.asyncio
async def test_review_decision_promotes_only_human_confirmed_scan() -> None:
    principal = actor("agronomist")
    review = AgronomistReviewQueue(
        id=uuid.uuid4(),
        scan_id=uuid.uuid4(),
        organization_id=principal.organization_id,
        reason="low_confidence",
        priority_score=100,
        status="pending",
        created_at=NOW,
    )
    embedding = ScanEmbedding(
        id=uuid.uuid4(),
        scan_id=review.scan_id,
        organization_id=principal.organization_id,
        embedding=[0.0] * 1024,
        created_at=NOW,
    )
    diagnosis = Diagnosis(
        scan_id=review.scan_id,
        organization_id=principal.organization_id,
        image_is_diagnosable=True,
        provider="provider",
        model_id="model",
        prompt_version="v1",
        token_usage={},
        full_response={"image_is_diagnosable": True},
    )
    db = FakeSession(scalar_values=[None, review, embedding, diagnosis])
    result = await reviews.decide_review(
        review.id,
        ReviewDecision(decision="corrected", confirmed_diagnosis="brown spot"),
        "review-key",
        principal,
        db,
    )
    assert result == {"status": "resolved"}
    assert embedding.confirmed_dx == "brown spot"
    assert diagnosis.full_response["agronomist_correction"] == "brown spot"

    listed = await reviews.list_reviews(
        principal,
        FakeSession(scalar_result_values=[[review]]),
    )
    assert listed == [review]


@pytest.mark.asyncio
async def test_document_ingestion_chunks_embeds_and_audits(monkeypatch: pytest.MonkeyPatch) -> None:
    principal = actor("super_admin")
    monkeypatch.setattr(
        documents.embedding_service,
        "embed_documents",
        AsyncMock(
            return_value=[
                StoredEmbeddings(
                    "document",
                    openai=EmbeddedText([0.1] * 1024, "openai", "text-embedding-3-small"),
                )
            ]
        ),
    )
    payload = DocumentIngest(
        title="Rice field guide",
        publisher="ICAR",
        licence="CC BY 4.0",
        source_url="https://example.com/guide",
        retrieved_at=NOW,
        tier=1,
        applicable_regions=["National", "national"],
        sections=[
            DocumentSectionInput(
                section="Prevention",
                page_number=7,
                content="Use clean seed and inspect the field regularly. " * 3,
            )
        ],
    )
    db = FakeSession()
    result = await documents.ingest_document(payload, principal, principal, db)
    assert result.chunk_count == 1
    assert result.applicable_regions == ["national"]
    assert db.commits == 1

    with pytest.raises(HTTPException):
        await documents.ingest_document(payload, actor("org_admin"), principal, FakeSession())
