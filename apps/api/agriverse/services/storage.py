from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from io import BytesIO
from typing import Any

import aioboto3  # type: ignore[import-untyped]
from botocore.exceptions import ClientError  # type: ignore[import-untyped]

from agriverse.config import get_settings

settings = get_settings()


class ObjectNotFoundError(Exception):
    pass


class ObjectStorage:
    def __init__(self) -> None:
        self._session = aioboto3.Session()

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
            return await client.generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": settings.s3_bucket,
                    "Key": object_key,
                    "ContentType": content_type,
                    "ServerSideEncryption": "AES256",
                },
                ExpiresIn=settings.presigned_url_seconds,
            )

    async def presign_download(self, object_key: str) -> str:
        async with self._client(public=True) as client:
            return await client.generate_presigned_url(
                "get_object",
                Params={"Bucket": settings.s3_bucket, "Key": object_key},
                ExpiresIn=settings.presigned_url_seconds,
            )

    async def head(self, object_key: str) -> dict[str, Any]:
        async with self._client() as client:
            try:
                return await client.head_object(Bucket=settings.s3_bucket, Key=object_key)
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
                return await stream.read()

    async def write_canonical_image(self, object_key: str, data: bytes) -> None:
        async with self._client() as client:
            await client.put_object(
                Bucket=settings.s3_bucket,
                Key=object_key,
                Body=BytesIO(data),
                ContentType="image/jpeg",
                ServerSideEncryption="AES256",
            )

    async def delete(self, object_key: str) -> None:
        async with self._client() as client:
            await client.delete_object(Bucket=settings.s3_bucket, Key=object_key)


storage = ObjectStorage()
