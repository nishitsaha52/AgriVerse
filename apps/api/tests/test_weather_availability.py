import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from agriverse.db import get_db
from agriverse.dependencies import get_current_principal
from agriverse.main import app
from agriverse.routers import weather
from agriverse.security import Principal
from agriverse.services.weather import WeatherUnavailableError
from tests.fakes import FakeSession


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        httpx.ConnectError("connection failed"),
        httpx.ReadTimeout("provider timed out"),
        httpx.HTTPStatusError(
            "provider unavailable",
            request=httpx.Request("GET", "https://weather.example"),
            response=httpx.Response(503),
        ),
        WeatherUnavailableError("no current conditions"),
    ],
)
async def test_provider_outage_returns_retryable_problem_without_saving_snapshot(
    monkeypatch, error
):
    principal = Principal(uuid.uuid4(), uuid.uuid4(), "org_admin", "en")
    db = FakeSession()
    field = SimpleNamespace(state="Karnataka", district="Mysuru", latitude=12.3, longitude=76.65)
    monkeypatch.setattr(weather, "authorize_field", AsyncMock(return_value=field))
    monkeypatch.setattr(weather.weather_service, "get_current", AsyncMock(side_effect=error))
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_db] = lambda: db
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(f"/api/v1/fields/{uuid.uuid4()}/weather")
    finally:
        app.dependency_overrides.pop(get_current_principal)
        app.dependency_overrides.pop(get_db)

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.headers["retry-after"] == "60"
    assert response.json()["detail"] == (
        "Weather service is temporarily unavailable. Please try again later."
    )
    assert db.added == []
    assert db.commits == 0
