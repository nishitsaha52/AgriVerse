import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from agriverse import dependencies
from agriverse.config import Settings
from agriverse.models import (
    Membership,
    OrganizationInvite,
    RefreshSession,
    User,
)
from agriverse.routers import auth
from agriverse.schemas import (
    FarmerLogin,
    FarmerPinReset,
    FarmerRegister,
    InviteCreate,
    OAuthExchangeRequest,
    RefreshRequest,
    StaffInviteCreate,
)
from agriverse.security import Principal, create_refresh_token, hash_pin, hash_token
from tests.fakes import FakeSession

NOW = datetime.now(UTC)


def actor(role: str = "field_agent") -> Principal:
    return Principal(uuid.uuid4(), uuid.uuid4(), role, "en")


def user_record(*, phone: str = "+919876543210", role: str = "farmer") -> tuple[User, Membership]:
    user = User(
        id=uuid.uuid4(),
        provider="phone",
        phone_e164=phone,
        pin_hash=hash_pin("123456"),
        preferred_language="en",
        failed_login_attempts=0,
        is_active=True,
        created_at=NOW,
    )
    membership = Membership(
        id=uuid.uuid4(),
        user_id=user.id,
        organization_id=uuid.uuid4(),
        role=role,
        created_at=NOW,
    )
    return user, membership


@pytest.mark.asyncio
async def test_current_principal_and_permission_matrix(monkeypatch: pytest.MonkeyPatch) -> None:
    user, membership = user_record()
    monkeypatch.setattr(
        dependencies,
        "decode_token",
        lambda token, token_type: {
            "sub": str(user.id),
            "org": str(membership.organization_id),
            "role": membership.role,
        },
    )
    db = FakeSession(execute_values=[[], [(user, membership)]])
    principal = await dependencies.get_current_principal(
        HTTPAuthorizationCredentials(scheme="Bearer", credentials="token"),
        db,
    )
    assert principal.user_id == user.id
    assert principal.role == "farmer"

    permitted = dependencies.require_permissions("field:read")
    assert await permitted(principal) == principal
    forbidden = dependencies.require_permissions("review:write")
    with pytest.raises(HTTPException) as denied:
        await forbidden(principal)
    assert denied.value.status_code == 403

    monkeypatch.setattr(dependencies.rate_limiter, "enforce_ai_quota", AsyncMock())
    assert await dependencies.enforce_ai_quota(principal) == principal


@pytest.mark.asyncio
async def test_farmer_register_login_lock_and_staff_bootstrap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization_id = uuid.uuid4()
    invite = OrganizationInvite(
        id=uuid.uuid4(),
        organization_id=organization_id,
        code_hash=hash_token("x" * 32),
        created_by=uuid.uuid4(),
        intended_role="farmer",
        expires_at=NOW + timedelta(hours=1),
        created_at=NOW,
    )
    monkeypatch.setattr(auth, "hash_pin", lambda pin: f"hashed:{pin}")
    register_db = FakeSession(scalar_values=[invite, None])
    registered = await auth.register_farmer(
        FarmerRegister(
            phone="+91 98765 43210",
            pin="123456",
            invite_code="x" * 32,
        ),
        register_db,
    )
    assert registered.organization_id == organization_id
    assert invite.used_at is not None

    with pytest.raises(HTTPException):
        await auth.register_farmer(
            FarmerRegister(
                phone="+91 98765 43210",
                pin="123456",
                invite_code="x" * 32,
            ),
            FakeSession(scalar_values=[invite]),
        )

    user, membership = user_record()
    login_payload = FarmerLogin(
        phone=user.phone_e164 or "",
        pin="123456",
        organization_id=membership.organization_id,
    )
    monkeypatch.setattr(auth, "verify_pin", lambda pin, encoded: True)
    logged_in = await auth.login_farmer(
        login_payload,
        FakeSession(scalar_values=[user, membership]),
    )
    assert logged_in.role == "farmer"

    monkeypatch.setattr(auth, "verify_pin", lambda pin, encoded: False)
    user.failed_login_attempts = 4
    with pytest.raises(HTTPException) as invalid:
        await auth.login_farmer(login_payload, FakeSession(scalar_values=[user]))
    assert invalid.value.status_code == 401
    assert user.locked_until is not None

    user.locked_until = NOW + timedelta(minutes=5)
    with pytest.raises(HTTPException) as locked:
        await auth.login_farmer(login_payload, FakeSession(scalar_values=[user]))
    assert locked.value.status_code == 423

    staff, staff_membership = user_record(role="agronomist")
    staff_payload = FarmerLogin(
        phone=staff.phone_e164 or "",
        pin="123456",
        organization_id=staff_membership.organization_id,
    )
    monkeypatch.setattr(auth, "verify_pin", lambda pin, encoded: True)
    result = await auth.staff_pin_login(
        staff_payload,
        FakeSession(scalar_values=[staff, staff_membership]),
    )
    assert result.role == "agronomist"


@pytest.mark.asyncio
@pytest.mark.parametrize("app_env", ["development", "production"])
async def test_staff_pin_login_rejects_inactive_and_locked_accounts(
    monkeypatch: pytest.MonkeyPatch,
    app_env: str,
) -> None:
    monkeypatch.setattr(auth.settings, "app_env", app_env)
    user, membership = user_record(role="org_admin")
    payload = FarmerLogin(
        phone=user.phone_e164 or "",
        pin="123456",
        organization_id=membership.organization_id,
    )
    monkeypatch.setattr(auth, "verify_pin", lambda pin, encoded: True)
    user.is_active = False
    with pytest.raises(HTTPException) as inactive:
        await auth.staff_pin_login(payload, FakeSession(scalar_values=[user]))
    assert inactive.value.status_code == 401
    user.is_active = True
    user.locked_until = NOW + timedelta(minutes=5)
    with pytest.raises(HTTPException) as locked:
        await auth.staff_pin_login(payload, FakeSession(scalar_values=[user]))
    assert locked.value.status_code == 423


@pytest.mark.asyncio
@pytest.mark.parametrize("app_env", ["development", "production"])
async def test_staff_pin_login_locks_after_failures_and_resets_after_success(
    monkeypatch: pytest.MonkeyPatch,
    app_env: str,
) -> None:
    monkeypatch.setattr(auth.settings, "app_env", app_env)
    user, membership = user_record(role="org_admin")
    payload = FarmerLogin(
        phone=user.phone_e164 or "",
        pin="123456",
        organization_id=membership.organization_id,
    )
    monkeypatch.setattr(auth, "verify_pin", lambda pin, encoded: False)
    user.failed_login_attempts = 4
    db = FakeSession(scalar_values=[user])
    with pytest.raises(HTTPException) as invalid:
        await auth.staff_pin_login(payload, db)
    assert invalid.value.status_code == 401
    assert user.failed_login_attempts == 5 and user.locked_until is not None
    assert db.commits == 1
    user.locked_until = NOW - timedelta(minutes=5)
    monkeypatch.setattr(auth, "verify_pin", lambda pin, encoded: True)
    result = await auth.staff_pin_login(
        payload,
        FakeSession(scalar_values=[user, membership]),
    )
    assert result.role == "org_admin"
    assert user.failed_login_attempts == 0 and user.locked_until is None


@pytest.mark.asyncio
async def test_staff_pin_login_works_in_production_without_oidc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = Settings(
        _env_file=None,
        app_env="production",
        jwt_secret="j" * 40,
        oauth_session_secret="o" * 40,
        gemini_api_key="test-gemini",
        google_client_id="",
        microsoft_client_id="",
        keycloak_client_id="",
        keycloak_issuer_url="",
        staff_pin_login_enabled=True,
    )
    monkeypatch.setattr(auth, "settings", config)
    registry = auth.create_oauth_clients(config)
    assert all(registry.create_client(name) is None for name in auth.OIDC_PROVIDERS)
    user, membership = user_record(role="org_admin")
    db = FakeSession(scalar_values=[user, membership])
    result = await auth.staff_pin_login(
        FarmerLogin(
            phone=user.phone_e164 or "", pin="123456", organization_id=membership.organization_id
        ),
        db,
    )
    assert result.role == "org_admin"
    assert result.organization_id == membership.organization_id
    assert result.access_token and result.refresh_token
    assert db.commits == 1
    assert any(isinstance(value, RefreshSession) for value in db.added)

    from agriverse.db import get_db
    from agriverse.main import app

    request_db = FakeSession(scalar_values=[user, membership])

    async def database():
        yield request_db

    monkeypatch.setitem(app.dependency_overrides, get_db, database)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://test",
    ) as client:
        response = await client.post(
            "/api/v1/auth/staff/pin-login",
            json={
                "phone": user.phone_e164,
                "pin": "123456",
                "organization_id": str(membership.organization_id),
            },
        )
    assert response.status_code == 200
    assert response.json()["role"] == "org_admin"
    assert request_db.commits == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("app_env", ["development", "production"])
async def test_staff_pin_can_be_disabled_explicitly(
    monkeypatch: pytest.MonkeyPatch, app_env: str
) -> None:
    monkeypatch.setattr(auth.settings, "app_env", app_env)
    monkeypatch.setattr(auth.settings, "staff_pin_login_enabled", False)
    db = FakeSession()
    payload = FarmerLogin(phone="+919876543210", pin="123456", organization_id=uuid.uuid4())
    with pytest.raises(HTTPException) as disabled:
        await auth.staff_pin_login(payload, db)
    assert disabled.value.status_code == 404
    assert db.commits == 0 and db.added == []


@pytest.mark.asyncio
async def test_staff_pin_requires_staff_membership(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth.settings, "app_env", "production")
    user, membership = user_record(role="org_admin")
    db = FakeSession(scalar_values=[user, None])
    with pytest.raises(HTTPException) as rejected:
        await auth.staff_pin_login(
            FarmerLogin(
                phone=user.phone_e164 or "",
                pin="123456",
                organization_id=membership.organization_id,
            ),
            db,
        )
    assert rejected.value.status_code == 401
    assert db.commits == 0 and db.added == []


@pytest.mark.asyncio
async def test_refresh_rotation_reuse_logout_invites_and_pin_reset() -> None:
    user, membership = user_record()
    token, token_id, expires_at = create_refresh_token(
        user.id,
        membership.organization_id,
        membership.role,
        is_staff=False,
    )
    session = RefreshSession(
        id=token_id,
        user_id=user.id,
        organization_id=membership.organization_id,
        token_hash=hash_token(token),
        expires_at=expires_at,
        created_at=NOW,
    )
    rotated = await auth.refresh_tokens(
        RefreshRequest(refresh_token=token),
        FakeSession(scalar_values=[session, membership]),
    )
    assert rotated.refresh_token != token
    assert session.revoked_at is not None
    assert session.replaced_by_id is not None

    active = RefreshSession(
        id=uuid.uuid4(),
        user_id=user.id,
        organization_id=membership.organization_id,
        token_hash="other",
        expires_at=NOW + timedelta(days=1),
        created_at=NOW,
    )
    with pytest.raises(HTTPException) as reused:
        await auth.refresh_tokens(
            RefreshRequest(refresh_token=token),
            FakeSession(scalar_values=[session], scalar_result_values=[[active]]),
        )
    assert "reuse" in str(reused.value.detail).lower()
    assert active.revoked_at is not None

    live_token, live_id, live_expiry = create_refresh_token(
        user.id,
        membership.organization_id,
        membership.role,
        is_staff=False,
    )
    live_session = RefreshSession(
        id=live_id,
        user_id=user.id,
        organization_id=membership.organization_id,
        token_hash=hash_token(live_token),
        expires_at=live_expiry,
        created_at=NOW,
    )
    await auth.logout(
        RefreshRequest(refresh_token=live_token),
        FakeSession(scalar_values=[live_session]),
    )
    assert live_session.revoked_at is not None

    principal = actor()
    farmer_invite = await auth.create_farmer_invite(
        InviteCreate(expires_in_hours=24),
        principal,
        FakeSession(),
    )
    assert farmer_invite.organization_id == principal.organization_id

    admin = actor("org_admin")
    staff_invite = await auth.create_staff_invite(
        StaffInviteCreate(
            email="AGRONOMIST@example.com",
            role="agronomist",
            expires_in_hours=24,
        ),
        admin,
        FakeSession(),
    )
    assert staff_invite.organization_id == admin.organization_id

    farmer, farmer_membership = user_record()
    farmer_membership.organization_id = principal.organization_id
    refresh = RefreshSession(
        id=uuid.uuid4(),
        user_id=farmer.id,
        organization_id=principal.organization_id,
        token_hash="token",
        expires_at=NOW + timedelta(days=1),
        created_at=NOW,
    )
    reset_db = FakeSession(
        scalar_values=[farmer_membership],
        get_values=[farmer],
        scalar_result_values=[[refresh]],
    )
    await auth.reset_farmer_pin(
        farmer.id,
        FarmerPinReset(new_pin="654321"),
        principal,
        reset_db,
    )
    assert refresh.revoked_at is not None
    assert farmer.failed_login_attempts == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["google", "microsoft", "keycloak"])
async def test_staff_oauth_existing_identity_and_exchange(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
) -> None:
    admin, membership = user_record(role="org_admin")
    admin.email = "admin@example.com"
    admin.oauth_subject = None
    oauth_client = SimpleNamespace(
        authorize_redirect=AsyncMock(return_value=SimpleNamespace(status_code=302)),
        authorize_access_token=AsyncMock(
            return_value={
                "userinfo": {
                    "sub": "subject-1",
                    "email": admin.email,
                    "email_verified": True,
                }
            }
        ),
    )
    monkeypatch.setattr(auth.oauth, "create_client", lambda provider: oauth_client)
    request = SimpleNamespace(session={})
    started = await auth.start_staff_oauth(
        provider,
        request,
        membership.organization_id,
    )
    assert started.status_code == 302
    assert request.session["staff_oauth"]["provider"] == provider

    request.session["staff_oauth"] = {
        "provider": provider,
        "organization_id": str(membership.organization_id),
        "invite_code": None,
    }
    monkeypatch.setattr(auth.oauth_exchange_store, "put", AsyncMock(return_value="exchange-code"))
    callback = await auth.complete_staff_oauth(
        provider,
        request,
        FakeSession(scalar_values=[admin, membership]),
    )
    assert callback.status_code == 303
    assert "exchange-code" in callback.headers["location"]
    if provider == "keycloak":
        assert admin.oauth_subject and admin.oauth_subject.startswith("keycloak:")
        assert admin.oauth_subject.endswith(":subject-1")
    else:
        assert admin.oauth_subject == f"{provider}:subject-1"

    token_pair = await auth.issue_token_pair(
        FakeSession(),
        user_id=admin.id,
        organization_id=membership.organization_id,
        role=membership.role,
    )
    monkeypatch.setattr(
        auth.oauth_exchange_store,
        "consume",
        AsyncMock(return_value=token_pair.model_dump(mode="json")),
    )
    exchanged = await auth.exchange_staff_oauth(OAuthExchangeRequest(code="x" * 32))
    assert exchanged.role == "org_admin"

    monkeypatch.setattr(auth.oauth_exchange_store, "consume", AsyncMock(return_value=None))
    with pytest.raises(HTTPException):
        await auth.exchange_staff_oauth(OAuthExchangeRequest(code="x" * 32))


@pytest.mark.parametrize("verified", [False, None])
async def test_keycloak_requires_verified_email(monkeypatch, verified):
    organization_id = uuid.uuid4()
    userinfo = {"sub": "subject", "email": "admin@example.com"}
    if verified is not None:
        userinfo["email_verified"] = verified
    monkeypatch.setattr(
        auth.oauth,
        "create_client",
        lambda name: SimpleNamespace(
            authorize_access_token=AsyncMock(return_value={"userinfo": userinfo}),
        ),
    )
    request = SimpleNamespace(
        session={
            "staff_oauth": {
                "provider": "keycloak",
                "organization_id": str(organization_id),
            }
        }
    )
    with pytest.raises(HTTPException) as rejected:
        await auth.complete_staff_oauth("keycloak", request, FakeSession())
    assert rejected.value.status_code == 401


async def test_keycloak_requires_an_invite_for_new_staff(monkeypatch):
    monkeypatch.setattr(
        auth.oauth,
        "create_client",
        lambda name: SimpleNamespace(
            authorize_access_token=AsyncMock(
                return_value={
                    "userinfo": {
                        "sub": "subject",
                        "email": "new@example.com",
                        "email_verified": True,
                    }
                }
            ),
        ),
    )
    request = SimpleNamespace(
        session={
            "staff_oauth": {
                "provider": "keycloak",
                "organization_id": str(uuid.uuid4()),
            }
        }
    )
    with pytest.raises(HTTPException) as rejected:
        await auth.complete_staff_oauth("keycloak", request, FakeSession())
    assert rejected.value.status_code == 403


def test_keycloak_discovery_and_pkce_configuration():
    from agriverse.config import Settings

    config = Settings(
        _env_file=None,
        keycloak_issuer_url="http://localhost:8080/realms/agriverse/",
        keycloak_client_id="agriverse-web",
    )
    registry = auth.create_oauth_clients(config)
    client = registry.create_client("keycloak")
    assert client._server_metadata_url == (
        "http://localhost:8080/realms/agriverse/.well-known/openid-configuration"
    )
    assert client.client_kwargs["code_challenge_method"] == "S256"
    assert client.client_kwargs["token_endpoint_auth_method"] == "none"
    assert auth.create_oauth_clients(Settings(_env_file=None)).create_client("keycloak") is None
