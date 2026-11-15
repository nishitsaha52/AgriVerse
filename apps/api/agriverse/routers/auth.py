import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from urllib.parse import quote

from authlib.integrations.starlette_client import OAuth, OAuthError  # type: ignore[import-untyped]
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from agriverse.audit import record_audit
from agriverse.config import Settings, get_settings
from agriverse.db import get_db
from agriverse.dependencies import require_permissions, set_tenant_context
from agriverse.http import ssl_context
from agriverse.models import (
    Membership,
    OrganizationInvite,
    RefreshSession,
    User,
)
from agriverse.schemas import (
    FarmerLogin,
    FarmerPinReset,
    FarmerRegister,
    InviteCreate,
    InviteCreated,
    OAuthExchangeRequest,
    RefreshRequest,
    StaffInviteCreate,
    TokenPair,
)
from agriverse.security import (
    Principal,
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_invite_code,
    hash_pin,
    hash_token,
    normalize_phone,
    verify_pin,
)
from agriverse.services.oauth_exchange import oauth_exchange_store

router = APIRouter(prefix="/auth", tags=["auth"])
STAFF_ROLES = {"field_agent", "agronomist", "org_admin", "support", "super_admin"}
settings = get_settings()
OIDC_PROVIDERS = {"google", "microsoft", "keycloak"}


def create_oauth_clients(config: Settings) -> OAuth:
    oauth = OAuth()
    if config.keycloak_issuer_url and config.keycloak_client_id:
        oauth.register(
            name="keycloak",
            client_id=config.keycloak_client_id,
            client_secret=config.keycloak_client_secret.get_secret_value() or None,
            server_metadata_url=(
                f"{config.keycloak_issuer_url.rstrip('/')}/.well-known/openid-configuration"
            ),
            client_kwargs={
                "scope": "openid email profile",
                "code_challenge_method": "S256",
                "verify": ssl_context(config.tls_ca_bundle),
                "token_endpoint_auth_method": (
                    "client_secret_basic"
                    if config.keycloak_client_secret.get_secret_value()
                    else "none"
                ),
            },
        )
    if config.google_client_id:
        oauth.register(
            name="google",
            client_id=config.google_client_id,
            client_secret=config.google_client_secret.get_secret_value(),
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={
                "scope": "openid email profile",
                "verify": ssl_context(config.tls_ca_bundle),
            },
        )
    if config.microsoft_client_id:
        oauth.register(
            name="microsoft",
            client_id=config.microsoft_client_id,
            client_secret=config.microsoft_client_secret.get_secret_value(),
            server_metadata_url=(
                "https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration"
            ),
            client_kwargs={
                "scope": "openid email profile",
                "verify": ssl_context(config.tls_ca_bundle),
            },
        )
    return oauth


oauth = create_oauth_clients(settings)


async def issue_token_pair(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    organization_id: uuid.UUID,
    role: str,
) -> TokenPair:
    access_token, _ = create_access_token(user_id, organization_id, role)
    refresh_token, token_id, refresh_expires = create_refresh_token(
        user_id,
        organization_id,
        role,
        is_staff=role in STAFF_ROLES,
    )
    db.add(
        RefreshSession(
            id=token_id,
            user_id=user_id,
            organization_id=organization_id,
            token_hash=hash_token(refresh_token),
            expires_at=refresh_expires,
        )
    )
    return TokenPair(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=15 * 60,
        organization_id=organization_id,
        role=role,
    )


@router.post("/farmer/register", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
async def register_farmer(
    payload: FarmerRegister,
    db: AsyncSession = Depends(get_db),
) -> TokenPair:
    invite_hash = hash_token(payload.invite_code)
    invite = await db.scalar(
        select(OrganizationInvite)
        .where(OrganizationInvite.code_hash == invite_hash)
        .with_for_update()
    )
    now = datetime.now(UTC)
    if (
        invite is None
        or invite.used_at is not None
        or invite.expires_at <= now
        or invite.intended_role != "farmer"
    ):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid invite")
    try:
        phone = normalize_phone(payload.phone)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    if await db.scalar(select(User.id).where(User.phone_e164 == phone)) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Phone already registered")

    await set_tenant_context(db, invite.organization_id)
    user = User(
        provider="phone",
        phone_e164=phone,
        pin_hash=hash_pin(payload.pin),
        preferred_language=payload.preferred_language,
    )
    db.add(user)
    await db.flush()
    db.add(
        Membership(
            user_id=user.id,
            organization_id=invite.organization_id,
            role="farmer",
        )
    )
    invite.used_at = now
    invite.used_by = user.id
    token_pair = await issue_token_pair(
        db,
        user_id=user.id,
        organization_id=invite.organization_id,
        role="farmer",
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Account conflict"
        ) from exc
    return token_pair


@router.post("/farmer/login", response_model=TokenPair)
async def login_farmer(
    payload: FarmerLogin,
    db: AsyncSession = Depends(get_db),
) -> TokenPair:
    try:
        phone = normalize_phone(payload.phone)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    user = await db.scalar(select(User).where(User.phone_e164 == phone))
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid phone, PIN, or organization",
    )
    if user is None or user.pin_hash is None or not user.is_active:
        raise invalid

    now = datetime.now(UTC)
    if user.locked_until is not None and user.locked_until > now:
        raise HTTPException(status_code=status.HTTP_423_LOCKED, detail="Account temporarily locked")
    if not verify_pin(payload.pin, user.pin_hash):
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= 5:
            delay_minutes = min(60, 2 ** (user.failed_login_attempts - 5))
            user.locked_until = now + timedelta(minutes=delay_minutes)
        await db.commit()
        raise invalid

    await set_tenant_context(db, payload.organization_id)
    membership = await db.scalar(
        select(Membership).where(
            Membership.user_id == user.id,
            Membership.organization_id == payload.organization_id,
            Membership.role == "farmer",
        )
    )
    if membership is None:
        raise invalid

    user.failed_login_attempts = 0
    user.locked_until = None
    token_pair = await issue_token_pair(
        db,
        user_id=user.id,
        organization_id=payload.organization_id,
        role=membership.role,
    )
    await db.commit()
    return token_pair


@router.post("/staff/pin-login", response_model=TokenPair)
async def staff_pin_login(
    payload: FarmerLogin,
    db: AsyncSession = Depends(get_db),
) -> TokenPair:
    """Sign in staff with phone/PIN and organization membership in any environment."""
    if not settings.staff_pin_login_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    try:
        phone = normalize_phone(payload.phone)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    user = await db.scalar(select(User).where(User.phone_e164 == phone))
    if user is None or user.pin_hash is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid login")
    now = datetime.now(UTC)
    if user.locked_until is not None and user.locked_until > now:
        raise HTTPException(status_code=status.HTTP_423_LOCKED, detail="Account temporarily locked")
    if not verify_pin(payload.pin, user.pin_hash):
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= 5:
            delay_minutes = min(60, 2 ** (user.failed_login_attempts - 5))
            user.locked_until = now + timedelta(minutes=delay_minutes)
        await db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid login")
    await set_tenant_context(db, payload.organization_id)
    membership = await db.scalar(
        select(Membership).where(
            Membership.user_id == user.id,
            Membership.organization_id == payload.organization_id,
            Membership.role.in_(STAFF_ROLES),
        )
    )
    if membership is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid login")
    user.failed_login_attempts = 0
    user.locked_until = None
    token_pair = await issue_token_pair(
        db,
        user_id=user.id,
        organization_id=payload.organization_id,
        role=membership.role,
    )
    await db.commit()
    return token_pair


@router.get("/staff/oauth/{provider}/start")
async def start_staff_oauth(
    provider: str,
    request: Request,
    organization_id: uuid.UUID,
    invite_code: str | None = None,
) -> RedirectResponse:
    client = oauth.create_client(provider) if provider in OIDC_PROVIDERS else None
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="OAuth provider is not configured",
        )
    request.session["staff_oauth"] = {
        "provider": provider,
        "organization_id": str(organization_id),
        "invite_code": invite_code,
    }
    redirect_uri = f"{settings.oauth_callback_base_url}/auth/staff/oauth/{provider}/callback"
    return cast(RedirectResponse, await client.authorize_redirect(request, redirect_uri))


@router.get("/staff/oauth/{provider}/callback")
async def complete_staff_oauth(
    provider: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    context = request.session.pop("staff_oauth", None)
    if (
        provider not in OIDC_PROVIDERS
        or not isinstance(context, dict)
        or context.get("provider") != provider
        or not isinstance(context.get("organization_id"), str)
    ):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OAuth state expired")
    client = oauth.create_client(provider)
    if client is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    try:
        token = await client.authorize_access_token(request)
    except OAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="OAuth authorization was rejected",
        ) from exc
    userinfo = token.get("userinfo")
    if not isinstance(userinfo, dict):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="The identity provider did not return an OpenID identity",
        )
    subject = userinfo.get("sub")
    email_value = userinfo.get("email") or (
        userinfo.get("preferred_username") if provider != "keycloak" else None
    )
    if not isinstance(subject, str) or not isinstance(email_value, str):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A verified email identity is required",
        )
    if userinfo.get("email_verified") is False or (
        provider == "keycloak" and userinfo.get("email_verified") is not True
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="The identity provider email is not verified",
        )
    email = email_value.strip().lower()
    if provider == "keycloak" and ("@" not in email or not subject):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email identity"
        )
    identity = f"{provider}:{subject}"
    if provider == "keycloak":
        issuer = hashlib.sha256(settings.keycloak_issuer_url.rstrip("/").encode()).hexdigest()
        identity = f"keycloak:{issuer}:{subject}"
    organization_id = uuid.UUID(context["organization_id"])
    await set_tenant_context(db, organization_id)
    user = await db.scalar(select(User).where(User.email == email))
    invite: OrganizationInvite | None = None
    if user is None:
        invite_code = context.get("invite_code")
        if not isinstance(invite_code, str):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="A staff invitation is required for first sign-in",
            )
        invite = await db.scalar(
            select(OrganizationInvite)
            .where(
                OrganizationInvite.code_hash == hash_token(invite_code),
                OrganizationInvite.organization_id == organization_id,
                OrganizationInvite.intended_email == email,
                OrganizationInvite.intended_role.in_(STAFF_ROLES),
            )
            .with_for_update()
        )
        now = datetime.now(UTC)
        if invite is None or invite.used_at is not None or invite.expires_at <= now:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Staff invitation is invalid or expired",
            )
        user = User(
            provider=provider,
            email=email,
            oauth_subject=identity,
        )
        db.add(user)
        await db.flush()
        db.add(
            Membership(
                user_id=user.id,
                organization_id=organization_id,
                role=invite.intended_role,
            )
        )
        invite.used_at = now
        invite.used_by = user.id
        role = invite.intended_role
    else:
        membership = await db.scalar(
            select(Membership).where(
                Membership.user_id == user.id,
                Membership.organization_id == organization_id,
                Membership.role.in_(STAFF_ROLES),
            )
        )
        if membership is None or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Staff membership is unavailable",
            )
        expected_subject = identity
        if user.oauth_subject not in {None, expected_subject}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This account is linked to a different identity",
            )
        user.provider = provider
        user.oauth_subject = expected_subject
        role = membership.role
    token_pair = await issue_token_pair(
        db,
        user_id=user.id,
        organization_id=organization_id,
        role=role,
    )
    await db.commit()
    exchange_code = await oauth_exchange_store.put(token_pair.model_dump(mode="json"))
    return RedirectResponse(
        f"{settings.web_oauth_callback_url}?code={quote(exchange_code)}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/staff/oauth/exchange", response_model=TokenPair)
async def exchange_staff_oauth(payload: OAuthExchangeRequest) -> TokenPair:
    stored: dict[str, Any] | None = await oauth_exchange_store.consume(payload.code)
    if stored is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="OAuth exchange code is invalid or expired",
        )
    return TokenPair.model_validate(stored)


@router.post("/refresh", response_model=TokenPair)
async def refresh_tokens(
    payload: RefreshRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenPair:
    claims = decode_token(payload.refresh_token, "refresh")
    try:
        user_id = uuid.UUID(claims["sub"])
        organization_id = uuid.UUID(claims["org"])
        token_id = uuid.UUID(claims["jti"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        ) from exc

    await set_tenant_context(db, organization_id)
    session = await db.scalar(
        select(RefreshSession).where(
            RefreshSession.id == token_id,
            RefreshSession.token_hash == hash_token(payload.refresh_token),
        )
    )
    now = datetime.now(UTC)
    if session is not None and session.revoked_at is not None:
        active_sessions = list(
            (
                await db.scalars(
                    select(RefreshSession).where(
                        RefreshSession.user_id == user_id,
                        RefreshSession.organization_id == organization_id,
                        RefreshSession.revoked_at.is_(None),
                    )
                )
            ).all()
        )
        for active_session in active_sessions:
            active_session.revoked_at = now
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token reuse detected; all sessions were revoked",
        )
    if session is None or session.expires_at <= now:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh expired")
    membership = await db.scalar(
        select(Membership).where(
            Membership.user_id == user_id,
            Membership.organization_id == organization_id,
        )
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Membership unavailable"
        )

    session.revoked_at = now
    token_pair = await issue_token_pair(
        db,
        user_id=user_id,
        organization_id=organization_id,
        role=membership.role,
    )
    # The self-referencing FK is immediate. Persist the replacement before
    # pointing the previous session at its ID; both writes stay in this transaction.
    await db.flush()
    replacement_claims = decode_token(token_pair.refresh_token, "refresh")
    session.replaced_by_id = uuid.UUID(replacement_claims["jti"])
    await db.commit()
    return token_pair


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    payload: RefreshRequest,
    db: AsyncSession = Depends(get_db),
) -> None:
    claims = decode_token(payload.refresh_token, "refresh")
    try:
        organization_id = uuid.UUID(claims["org"])
        token_id = uuid.UUID(claims["jti"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        ) from exc
    await set_tenant_context(db, organization_id)
    refresh_session = await db.scalar(
        select(RefreshSession).where(
            RefreshSession.id == token_id,
            RefreshSession.organization_id == organization_id,
            RefreshSession.token_hash == hash_token(payload.refresh_token),
        )
    )
    if refresh_session is not None and refresh_session.revoked_at is None:
        refresh_session.revoked_at = datetime.now(UTC)
        await db.commit()


@router.post("/invites", response_model=InviteCreated, status_code=status.HTTP_201_CREATED)
async def create_farmer_invite(
    payload: InviteCreate,
    principal: Principal = Depends(require_permissions("farmer:onboard")),
    db: AsyncSession = Depends(get_db),
) -> InviteCreated:
    raw_code = generate_invite_code()
    expires_at = datetime.now(UTC) + timedelta(hours=payload.expires_in_hours)
    db.add(
        OrganizationInvite(
            organization_id=principal.organization_id,
            code_hash=hash_token(raw_code),
            created_by=principal.user_id,
            intended_role="farmer",
            expires_at=expires_at,
        )
    )
    await db.commit()
    return InviteCreated(
        code=raw_code,
        organization_id=principal.organization_id,
        expires_at=expires_at,
    )


@router.post(
    "/staff/invites",
    response_model=InviteCreated,
    status_code=status.HTTP_201_CREATED,
)
async def create_staff_invite(
    payload: StaffInviteCreate,
    principal: Principal = Depends(require_permissions("farmer:onboard")),
    db: AsyncSession = Depends(get_db),
) -> InviteCreated:
    if principal.role not in {"org_admin", "super_admin"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")
    raw_code = generate_invite_code()
    expires_at = datetime.now(UTC) + timedelta(hours=payload.expires_in_hours)
    db.add(
        OrganizationInvite(
            organization_id=principal.organization_id,
            code_hash=hash_token(raw_code),
            created_by=principal.user_id,
            intended_role=payload.role,
            intended_email=payload.email.strip().lower(),
            expires_at=expires_at,
        )
    )
    await db.commit()
    return InviteCreated(
        code=raw_code,
        organization_id=principal.organization_id,
        expires_at=expires_at,
    )


@router.post("/farmers/{user_id}/reset-pin", status_code=status.HTTP_204_NO_CONTENT)
async def reset_farmer_pin(
    user_id: uuid.UUID,
    payload: FarmerPinReset,
    principal: Principal = Depends(require_permissions("farmer:onboard")),
    db: AsyncSession = Depends(get_db),
) -> None:
    membership = await db.scalar(
        select(Membership).where(
            Membership.user_id == user_id,
            Membership.organization_id == principal.organization_id,
            Membership.role == "farmer",
        )
    )
    user = await db.get(User, user_id) if membership is not None else None
    if user is None or user.provider != "phone":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Farmer not found")
    user.pin_hash = hash_pin(payload.new_pin)
    user.failed_login_attempts = 0
    user.locked_until = None
    sessions = list(
        (
            await db.scalars(
                select(RefreshSession).where(
                    RefreshSession.user_id == user.id,
                    RefreshSession.organization_id == principal.organization_id,
                    RefreshSession.revoked_at.is_(None),
                )
            )
        ).all()
    )
    now = datetime.now(UTC)
    for refresh_session in sessions:
        refresh_session.revoked_at = now
    record_audit(
        db,
        principal,
        action="farmer.pin_reset",
        resource_type="user",
        resource_id=user.id,
        after={"sessions_revoked": len(sessions)},
    )
    await db.commit()
