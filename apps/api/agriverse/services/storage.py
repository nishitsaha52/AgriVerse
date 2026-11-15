from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from io import BytesIO
from typing import Any, cast

import aioboto3  # type: ignore[import-untyped]
from botocore.exceptions import ClientError  # type: ignore[import-untyped]

from agriverse.config import get_settings
from agriverse.http import trusted_ca_file

settings = get_settings()


class ObjectNotFoundError(Exception):
    pass


class ObjectStorage:
    def __init__(self) -> None:
        self._session = aioboto3.Session()

    def _encryption_args(self) -> dict[str, str]:
        if settings.s3_server_side_encryption == "AES256":
            return {"ServerSideEncryption": "AES256"}
        return {}

    def upload_headers(self, content_type: str) -> dict[str, str]:
        headers = {"Content-Type": content_type}
        if settings.s3_server_side_encryption == "AES256":
            headers["x-amz-server-side-encryption"] = "AES256"
        return headers

    @asynccontextmanager
    async def _client(self, *, public: bool = False) -> AsyncIterator[Any]:
        endpoint = (
            settings.s3_public_endpoint_url
            if public and settings.s3_public_endpoint_url
            else settings.s3_endpoint_url
        )
        async with self._session.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=settings.s3_access_key_id.get_secret_value(),
            aws_secret_access_key=settings.s3_secret_access_key.get_secret_value(),
            region_name=settings.s3_region,
            verify=trusted_ca_file(settings.tls_ca_bundle),
        ) as client:
            yield client

    async def ensure_bucket(self) -> None:
        async with self._client() as client:
            try:
                await client.head_bucket(Bucket=settings.s3_bucket)
            except ClientError as exc:
                code = str(exc.response.get("Error", {}).get("Code", ""))
                if code not in {"404", "NoSuchBucket", "NotFound"}:
                    raise
                await client.create_bucket(Bucket=settings.s3_bucket)

    async def presign_upload(self, object_key: str, content_type: str) -> str:
        async with self._client(public=True) as client:
            return cast(
                str,
                await client.generate_presigned_url(
                    "put_object",
                    Params={
                        "Bucket": settings.s3_bucket,
                        "Key": object_key,
                        "ContentType": content_type,
                        **self._encryption_args(),
                    },
                    ExpiresIn=settings.presigned_url_seconds,
                ),
            )

    async def presign_download(self, object_key: str) -> str:
        async with self._client(public=True) as client:
            return cast(
                str,
                await client.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": settings.s3_bucket, "Key": object_key},
                    ExpiresIn=settings.presigned_url_seconds,
                ),
            )

    async def head(self, object_key: str) -> dict[str, Any]:
        async with self._client() as client:
            try:
                return cast(
                    dict[str, Any],
                    await client.head_object(Bucket=settings.s3_bucket, Key=object_key),
                )
            except ClientError as exc:
                code = str(exc.response.get("Error", {}).get("Code", ""))
                if code in {"404", "NoSuchKey", "NotFound"}:
                    raise ObjectNotFoundError(object_key) from exc
                raise

    async def read(self, object_key: str) -> bytes:
        async with self._client() as client:
            try:
                response = await client.get_object(Bucket=settings.s3_bucket, Key=object_key)
            except ClientError as exc:
                code = str(exc.response.get("Error", {}).get("Code", ""))
                if code in {"404", "NoSuchKey", "NotFound"}:
                    raise ObjectNotFoundError(object_key) from exc
                raise
            async with response["Body"] as stream:
                return cast(bytes, await stream.read())

    async def write_canonical_image(self, object_key: str, data: bytes) -> None:
        async with self._client() as client:
            await client.put_object(
                Bucket=settings.s3_bucket,
                Key=object_key,
                Body=BytesIO(data),
                ContentType="image/jpeg",
                **self._encryption_args(),
            )

    async def delete(self, object_key: str) -> None:
        async with self._client() as client:
            await client.delete_object(Bucket=settings.s3_bucket, Key=object_key)


storage = ObjectStorage()
