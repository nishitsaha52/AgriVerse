import re

import httpx
import pytest

from agriverse.main import app


@pytest.mark.asyncio
async def test_swagger_policy_allows_assets_and_only_its_inline_initializer() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await client.get("/docs")
        second = await client.get("/docs")
        health = await client.get("/healthz")

    assert first.status_code == 200
    nonce = re.search(r'<script nonce="([^"]+)">', first.text)
    assert nonce is not None
    policy = first.headers["content-security-policy"]
    script_policy = next(part.strip() for part in policy.split(";") if "script-src" in part)
    assert f"'nonce-{nonce[1]}'" in script_policy
    assert "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/" in script_policy
    assert "'unsafe-inline'" not in script_policy
    assert "style-src 'self' https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/" in policy
    assert nonce[1] not in second.text
    assert first.headers["cache-control"] == "no-store"
    assert "cdn.jsdelivr.net" not in health.headers["content-security-policy"]
    assert "/docs" not in app.openapi()["paths"]


@pytest.mark.asyncio
async def test_swagger_schema_url_preserves_proxy_root_path() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, root_path="/agriverse"), base_url="http://test"
    ) as client:
        response = await client.get("/docs")
    assert response.status_code == 200
    assert "url: '/agriverse/openapi.json'" in response.text
