import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt
import phonenumbers
from fastapi import HTTPException, status
from pwdlib import PasswordHash

from agriverse.config import get_settings

settings = get_settings()
password_hash = PasswordHash.recommended()


@dataclass(frozen=True)
class Principal:
    user_id: uuid.UUID
    organization_id: uuid.UUID
    role: str
    preferred_language: str


def normalize_phone(raw_phone: str, default_region: str = "IN") -> str:
    try:
        parsed = phonenumbers.parse(raw_phone, default_region)
    except phonenumbers.NumberParseException as exc:
        raise ValueError("Invalid phone number") from exc
    if not phonenumbers.is_valid_number(parsed):
        raise ValueError("Invalid phone number")
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def hash_pin(pin: str) -> str:
    return password_hash.hash(pin)


def verify_pin(pin: str, encoded: str) -> bool:
    return password_hash.verify(pin, encoded)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_invite_code() -> str:
    return secrets.token_urlsafe(32)


def _encode_token(
    *,
    user_id: uuid.UUID,
    organization_id: uuid.UUID,
    role: str,
    token_type: Literal["access", "refresh"],
    expires_at: datetime,
    token_id: uuid.UUID,
) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "org": str(organization_id),
        "role": role,
        "type": token_type,
        "jti": str(token_id),
        "iat": now,
        "nbf": now,
        "exp": expires_at,
        "iss": "agriverse",
        "aud": "agriverse-app",
    }
    return jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm="HS256")


def create_access_token(
    user_id: uuid.UUID, organization_id: uuid.UUID, role: str
) -> tuple[str, datetime]:
    expires_at = datetime.now(UTC) + timedelta(minutes=settings.access_token_minutes)
    return (
        _encode_token(
            user_id=user_id,
            organization_id=organization_id,
            role=role,
            token_type="access",
            expires_at=expires_at,
            token_id=uuid.uuid4(),
        ),
        expires_at,
    )


def create_refresh_token(
    user_id: uuid.UUID,
    organization_id: uuid.UUID,
    role: str,
    *,
    is_staff: bool,
) -> tuple[str, uuid.UUID, datetime]:
    days = settings.staff_refresh_days if is_staff else settings.farmer_refresh_days
    expires_at = datetime.now(UTC) + timedelta(days=days)
    token_id = uuid.uuid4()
    token = _encode_token(
        user_id=user_id,
        organization_id=organization_id,
        role=role,
        token_type="refresh",
        expires_at=expires_at,
        token_id=token_id,
    )
    return token, token_id, expires_at


def decode_token(token: str, expected_type: Literal["access", "refresh"]) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=["HS256"],
            audience="agriverse-app",
            issuer="agriverse",
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    if payload.get("type") != expected_type:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")
    return payload
