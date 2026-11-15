from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(Path(__file__).resolve().parents[3] / ".env", ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "AgriVerse API"
    app_env: Literal["development", "test", "staging", "production"] = "development"
    api_v1_prefix: str = "/api/v1"
    web_origin: str = "http://localhost:3001"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3001"])

    bootstrap_name: str | None = None
    bootstrap_phone: str | None = None
    bootstrap_pin: SecretStr = SecretStr("")
    bootstrap_email: str | None = None

    database_url: str = "postgresql+asyncpg://agriverse:agriverse@localhost:5432/agriverse"
    migration_database_url: str | None = None
    tls_ca_bundle: str | None = None
    redis_url: str = "redis://localhost:6379/0"
    user_requests_per_minute: int = 60
    organization_requests_per_minute: int = 600
    organization_ai_calls_per_day: int = 500

    jwt_secret: SecretStr = SecretStr("development-only-change-this-secret")
    oauth_session_secret: SecretStr = SecretStr("development-oauth-session-secret")
    access_token_minutes: int = 15
    farmer_refresh_days: int = 60
    staff_refresh_days: int = 7
    staff_pin_login_enabled: bool = True

    s3_endpoint_url: str = "http://localhost:9000"
    s3_public_endpoint_url: str | None = None
    s3_access_key_id: SecretStr = SecretStr("minioadmin")
    s3_secret_access_key: SecretStr = SecretStr("minioadmin")
    s3_bucket: str = "agriverse"
    s3_region: str = "us-east-1"
    s3_server_side_encryption: Literal["AES256", "none"] = "AES256"
    presigned_url_seconds: int = 300
    max_image_bytes: int = 10 * 1024 * 1024
    max_image_pixels: int = 25_000_000

    openai_api_key: SecretStr = SecretStr("")
    openai_gate_model: str = "gpt-5.6-luna"
    openai_vision_model: str = "gpt-5.6-terra"
    openai_agent_model: str = "gpt-5.6-sol"

    openai_embedding_model: str = "text-embedding-3-small"
    openai_rerank_model: str = "gpt-5.6-luna"
    gemini_api_key: SecretStr = SecretStr("")
    gemini_gate_model: str = "gemini-3.8-flash"
    gemini_vision_model: str = "gemini-3.8-flash"
    gemini_agent_model: str = "gemini-3.8-flash"
    gemini_rerank_model: str = "gemini-3.8-flash"
    gemini_embedding_model: str = "gemini-embedding-001"
    ai_timeout_seconds: float = Field(default=45, gt=0)
    vector_dimension: int = Field(default=1024, ge=1, le=2000)

    open_meteo_base_url: str = "https://api.open-meteo.com/v1"

    otel_exporter_otlp_endpoint: str | None = None
    otel_service_name: str = "agriverse-api"
    langfuse_host: str | None = None
    langfuse_public_key: str | None = None
    langfuse_secret_key: SecretStr = SecretStr("")

    google_client_id: str | None = None
    google_client_secret: SecretStr = SecretStr("")
    microsoft_client_id: str | None = None
    microsoft_client_secret: SecretStr = SecretStr("")
    keycloak_issuer_url: str = ""
    keycloak_client_id: str = ""
    keycloak_client_secret: SecretStr = SecretStr("")
    oauth_callback_base_url: str = "http://localhost:8000/api/v1"
    web_oauth_callback_url: str = "http://localhost:3001/api/oauth/callback"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_cors_origins(cls, value: object) -> object:
        if isinstance(value, str) and not value.lstrip().startswith("["):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @model_validator(mode="after")
    def validate_storage_encryption(self) -> "Settings":
        if self.s3_server_side_encryption == "none" and self.app_env not in {
            "development",
            "test",
        }:
            raise ValueError(
                "S3_SERVER_SIDE_ENCRYPTION=none is only allowed in development or test"
            )
        return self

    @model_validator(mode="after")
    def validate_production_secrets(self) -> "Settings":
        if self.app_env == "production":
            secret = self.jwt_secret.get_secret_value()
            if len(secret) < 32 or secret.startswith("development-only"):
                raise ValueError("JWT_SECRET must be a random value of at least 32 characters")
            if not (
                self.openai_api_key.get_secret_value() or self.gemini_api_key.get_secret_value()
            ):
                raise ValueError("OPENAI_API_KEY or GEMINI_API_KEY must be supplied in production")
            if len(self.oauth_session_secret.get_secret_value()) < 32:
                raise ValueError("OAUTH_SESSION_SECRET must contain at least 32 characters")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
