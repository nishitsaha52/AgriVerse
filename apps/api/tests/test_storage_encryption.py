from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from agriverse.config import Settings
from agriverse.routers import scans
from agriverse.schemas import ScanCreate
from agriverse.services import storage as storage_module
from agriverse.services.storage import ObjectStorage
from tests.fakes import FakeSession
from tests.test_routes import actor, farm_record, field_record


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["AES256", "none"])
async def test_upload_signature_headers_and_processed_write_use_same_encryption(monkeypatch, mode):
    config = Settings(_env_file=None, app_env="development", s3_server_side_encryption=mode)
    monkeypatch.setattr(storage_module, "settings", config)
    storage = ObjectStorage()
    client = SimpleNamespace(
        generate_presigned_url=AsyncMock(return_value="https://objects.example/upload"),
        put_object=AsyncMock(),
    )

    @asynccontextmanager
    async def fake_client(*, public=False):
        yield client

    monkeypatch.setattr(storage, "_client", fake_client)
    await storage.presign_upload("original.png", "image/png")
    params = client.generate_presigned_url.await_args.kwargs["Params"]
    headers = storage.upload_headers("image/png")
    await storage.write_canonical_image("processed.jpg", b"processed-image")
    write_args = client.put_object.await_args.kwargs

    assert params["ContentType"] == headers["Content-Type"] == "image/png"
    assert write_args["ContentType"] == "image/jpeg"
    assert write_args["Body"].getvalue() == b"processed-image"
    if mode == "AES256":
        assert params["ServerSideEncryption"] == "AES256"
        assert headers["x-amz-server-side-encryption"] == "AES256"
        assert write_args["ServerSideEncryption"] == "AES256"
    else:
        assert "ServerSideEncryption" not in params
        assert "x-amz-server-side-encryption" not in headers
        assert "ServerSideEncryption" not in write_args


@pytest.mark.asyncio
async def test_scan_creation_returns_headers_for_explicit_development_mode(monkeypatch):
    config = Settings(_env_file=None, app_env="development", s3_server_side_encryption="none")
    monkeypatch.setattr(storage_module, "settings", config)
    monkeypatch.setattr(scans.storage, "presign_upload", AsyncMock(return_value="https://upload"))
    principal = actor()
    field = field_record(principal, farm_record(principal))
    result = await scans.create_scan(
        field.id,
        ScanCreate(filename="test.png", content_type="image/png"),
        principal,
        FakeSession(scalar_values=[field]),
    )
    assert result.required_headers == {"Content-Type": "image/png"}


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_unencrypted_storage_is_rejected_outside_local_testing(environment):
    with pytest.raises(ValidationError, match="only allowed in development or test"):
        Settings(_env_file=None, app_env=environment, s3_server_side_encryption="none")


def test_encryption_is_enabled_by_default():
    assert Settings(_env_file=None).s3_server_side_encryption == "AES256"
