import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class Problem(ApiModel):
    type: str = "about:blank"
    title: str
    status: int
    detail: str
    instance: str | None = None
    request_id: str | None = None


class TokenPair(ApiModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    organization_id: uuid.UUID
    role: str


class FarmerRegister(ApiModel):
    phone: str = Field(min_length=8, max_length=24)
    pin: str = Field(pattern=r"^\d{6,12}$")
    invite_code: str = Field(min_length=24, max_length=128)
    preferred_language: str = Field(default="en", min_length=2, max_length=12)


class FarmerLogin(ApiModel):
    phone: str = Field(min_length=8, max_length=24)
    pin: str = Field(pattern=r"^\d{6,12}$")
    organization_id: uuid.UUID


class FarmerPinReset(ApiModel):
    new_pin: str = Field(pattern=r"^\d{6,12}$")


class RefreshRequest(ApiModel):
    refresh_token: str


class InviteCreate(ApiModel):
    expires_in_hours: int = Field(default=72, ge=1, le=720)


class InviteCreated(ApiModel):
    code: str
    organization_id: uuid.UUID
    expires_at: datetime


class StaffInviteCreate(ApiModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=320)
    role: Literal["field_agent", "agronomist", "org_admin", "support"]
    expires_in_hours: int = Field(default=72, ge=1, le=168)


class OAuthExchangeRequest(ApiModel):
    code: str = Field(min_length=32, max_length=256)


class FarmCreate(ApiModel):
    name: str = Field(min_length=2, max_length=160)
    owner_user_id: uuid.UUID | None = None


class FarmUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    owner_user_id: uuid.UUID | None = None


class FarmRead(ApiModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    owner_user_id: uuid.UUID | None
    created_at: datetime


Latitude = Annotated[Decimal, Field(ge=Decimal("-90"), le=Decimal("90"))]
Longitude = Annotated[Decimal, Field(ge=Decimal("-180"), le=Decimal("180"))]


class FieldCreate(ApiModel):
    farm_id: uuid.UUID
    name: str = Field(min_length=2, max_length=160)
    latitude: Latitude
    longitude: Longitude
    state: str = Field(min_length=2, max_length=80)
    district: str = Field(min_length=2, max_length=120)
    agro_climatic_zone: str = Field(min_length=2, max_length=120)
    current_crop: Literal["rice", "wheat", "tomato"] | None = None


class FieldUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    latitude: Latitude | None = None
    longitude: Longitude | None = None
    state: str | None = Field(default=None, min_length=2, max_length=80)
    district: str | None = Field(default=None, min_length=2, max_length=120)
    agro_climatic_zone: str | None = Field(default=None, min_length=2, max_length=120)
    current_crop: Literal["rice", "wheat", "tomato"] | None = None


class FieldRead(ApiModel):
    id: uuid.UUID
    farm_id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    latitude: Decimal
    longitude: Decimal
    state: str
    district: str
    agro_climatic_zone: str
    current_crop: str | None
    created_at: datetime


Nutrient = Annotated[Decimal, Field(ge=0, le=10000, max_digits=10, decimal_places=3)]


class SoilTestCreate(ApiModel):
    n: Nutrient
    p: Nutrient
    k: Nutrient
    ph: Annotated[Decimal, Field(ge=0, le=14, max_digits=5, decimal_places=2)]
    ec: Nutrient
    oc: Nutrient
    s: Nutrient
    zn: Nutrient
    fe: Nutrient
    cu: Nutrient
    mn: Nutrient
    b: Nutrient


class CropScore(ApiModel):
    crop: Literal["rice", "wheat", "tomato"]
    score: float = Field(ge=0, le=100)
    reasons: list[str]


class SoilTestRead(SoilTestCreate):
    id: uuid.UUID
    field_id: uuid.UUID
    organization_id: uuid.UUID
    fertility_index: Decimal
    algorithm_version: str
    created_at: datetime
    ranked_crops: list[CropScore] = Field(default_factory=list)
    algorithm_sources: list[str] = Field(default_factory=list)


class WeatherPoint(ApiModel):
    observed_at: datetime
    temperature_c: float
    relative_humidity_pct: float | None = None
    precipitation_mm: float = 0
    wind_speed_kph: float = 0


class WeatherAlertRead(ApiModel):
    alert_type: str
    severity: Literal["info", "warning", "critical"]
    message: str
    source_url: str | None = None


class ForecastRead(ApiModel):
    source: str
    fetched_at: datetime
    current: WeatherPoint
    forecast: list[WeatherPoint] = Field(default_factory=list)
    alerts: list[WeatherAlertRead]


class ScanCreate(ApiModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: Literal["image/jpeg", "image/png", "image/webp"]


class ScanUpload(ApiModel):
    scan_id: uuid.UUID
    upload_url: str
    object_key: str
    expires_in: int
    required_headers: dict[str, str]


class Citation(ApiModel):
    chunk_id: uuid.UUID | None = None
    publisher: str
    title: str
    page: int | None = None
    section: str | None = None
    licence: str
    source_url: HttpUrl | str
    tier: Literal[1, 2, 3]


class Alternative(ApiModel):
    condition: str
    why_considered: str
    why_less_likely: str


class PrimaryCondition(ApiModel):
    condition: str
    category: Literal["disease", "pest", "nutrient_deficiency", "abiotic_stress", "healthy"]
    confidence: Literal["high", "moderate", "low"]
    visual_evidence: str


class DiagnosisResult(ApiModel):
    image_is_diagnosable: bool
    rejection_reason: str | None = None
    primary: PrimaryCondition | None = None
    differential: list[Alternative] = Field(default_factory=list, max_length=3)
    immediate_actions: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    requires_expert: bool = False

    @model_validator(mode="after")
    def enforce_diagnosability(self) -> "DiagnosisResult":
        if self.image_is_diagnosable and self.primary is None:
            raise ValueError("primary is required for a diagnosable image")
        if not self.image_is_diagnosable and not self.rejection_reason:
            raise ValueError("rejection_reason is required when the image is not diagnosable")
        return self


class ScanRead(ApiModel):
    id: uuid.UUID
    field_id: uuid.UUID
    status: Literal["pending", "processing", "completed", "rejected", "failed"]
    created_at: datetime
    diagnosis: DiagnosisResult | None = None
    failure_code: str | None = None


class FeedbackCreate(ApiModel):
    outcome: Literal["worked", "failed", "unsure"]
    notes: str | None = Field(default=None, max_length=2000)


class ReviewRead(ApiModel):
    id: uuid.UUID
    scan_id: uuid.UUID
    reason: str
    priority_score: int
    status: str
    assigned_to: uuid.UUID | None
    created_at: datetime


class ReviewDecision(ApiModel):
    decision: Literal["confirmed", "corrected", "indeterminate"]
    confirmed_diagnosis: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def validate_label(self) -> "ReviewDecision":
        if self.decision in {"confirmed", "corrected"} and not self.confirmed_diagnosis:
            raise ValueError("confirmed_diagnosis is required for this decision")
        return self


class AgentQuestion(ApiModel):
    field_id: uuid.UUID
    conversation_id: uuid.UUID | None = None
    question: str = Field(min_length=2, max_length=4000)
    language: str = Field(default="en", min_length=2, max_length=12)


class AgentAnswer(ApiModel):
    conversation_id: uuid.UUID
    answer: str
    citations: list[Citation]


class DocumentSectionInput(ApiModel):
    section: str = Field(min_length=1, max_length=255)
    page_number: int | None = Field(default=None, ge=1)
    content: str = Field(min_length=20, max_length=250_000)


class DocumentIngest(ApiModel):
    title: str = Field(min_length=2, max_length=255)
    publisher: str = Field(min_length=2, max_length=255)
    licence: str = Field(min_length=2, max_length=120)
    source_url: HttpUrl
    retrieved_at: datetime
    tier: Literal[1, 2, 3]
    applicable_regions: list[str] = Field(min_length=1, max_length=100)
    sections: list[DocumentSectionInput] = Field(min_length=1, max_length=200)


class DocumentRead(ApiModel):
    id: uuid.UUID
    title: str
    publisher: str
    licence: str
    source_url: str
    retrieved_at: datetime
    tier: int
    applicable_regions: list[str]
    chunk_count: int


class OrganizationRead(ApiModel):
    id: uuid.UUID
    name: str
    licence_tier: str
    is_active: bool


class MembershipRead(ApiModel):
    user_id: uuid.UUID
    organization_id: uuid.UUID
    role: str
    created_at: datetime


class UsageRead(ApiModel):
    id: uuid.UUID
    user_id: uuid.UUID | None
    call_type: str
    tokens_used: int
    cost_usd: Decimal
    request_id: str | None
    created_at: datetime


class AuditRead(ApiModel):
    id: int
    actor_user_id: uuid.UUID | None
    action: str
    resource_type: str
    resource_id: str | None
    before: dict[str, object] | None
    after: dict[str, object] | None
    request_id: str | None
    created_at: datetime
