"""Explicit live diagnostics; optional integrations require command-line opt-in.

Run from the API environment. Reads the normal application settings, makes small
billable LLM requests, and only deletes temporary Redis keys/S3 objects it creates.
It never changes database data, buckets, accounts, or configuration. Reports omit
credentials, signed URLs, model answers and identity-provider tokens.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import importlib
import io
import json
import math
import re
import secrets
import ssl
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import aioboto3
import httpx
from botocore.config import Config
from PIL import Image
from pydantic import SecretStr
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from agriverse.config import get_settings
from agriverse.http import ssl_context


class Diagnostics:
    def __init__(self, args):
        self.args = args
        self.settings = get_settings()
        self.run_id = str(uuid.uuid4())
        self.started = datetime.now(UTC).isoformat()
        self.results = []
        self.output = Path(args.output).resolve()
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.trusted = ssl_context(self.settings.tls_ca_bundle)
        self.gemini_generation = None
        image = Image.new("RGB", (128, 128), (40, 160, 60))
        buf = io.BytesIO()
        image.save(buf, format="JPEG")
        self.image = buf.getvalue()

    def record(self, service, check, status, **detail):
        row = dict(service=service, check=check, status=status, **detail)
        self.results.append(row)
        self.output.write_text(
            json.dumps(
                dict(
                    run_id=self.run_id,
                    started_utc=self.started,
                    updated_utc=datetime.now(UTC).isoformat(),
                    results=self.results,
                ),
                indent=2,
            ),
            encoding="utf-8",
        )
        print(json.dumps(row), flush=True)
        return row

    @staticmethod
    def error(exc):
        # Do not stringify arbitrary SDK exceptions: some contain credentials/URLs.
        data = {"error_type": type(exc).__name__}
        status = getattr(exc, "status_code", None)
        response = getattr(exc, "response", None)
        if isinstance(response, httpx.Response):
            status = response.status_code
            try:
                err = response.json().get("error", {})
                if isinstance(err, dict):
                    for key in ("code", "type", "status"):
                        value = err.get(key)
                        if isinstance(value, (int, str)) and len(str(value)) < 100:
                            data[key] = value
            except (ValueError, AttributeError):
                # Extract only an alphanumeric error code; never parse untrusted XML.
                body = response.text[:8192]
                code = re.search(r"<Code>([A-Za-z0-9_]{1,99})</Code>", body)
                if code:
                    data["code"] = code.group(1)
                if "S3 API Requests must be made to API port" in body:
                    data["diagnostic"] = "S3 API Requests must be made to API port."
        elif isinstance(response, dict):
            data["code"] = response.get("Error", {}).get("Code")
            status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if status:
            data["http_status"] = status
        cause = exc
        while cause is not None:
            if isinstance(
                cause, ssl.SSLCertVerificationError
            ) or "CERTIFICATE_VERIFY_FAILED" in str(cause):
                data["diagnostic"] = (
                    "TLS certificate chain is not trusted by the default Python HTTP client."
                )
                break
            cause = cause.__cause__
        return data

    async def check(self, service, name, fn):
        start = time.monotonic()
        try:
            detail = await fn()
            return self.record(
                service, name, "PASS", seconds=round(time.monotonic() - start, 2), **(detail or {})
            )
        except Exception as exc:
            return self.record(
                service, name, "FAIL", seconds=round(time.monotonic() - start, 2), **self.error(exc)
            )

    async def database(self):
        engine = create_async_engine(
            self.settings.database_url, poolclass=NullPool, connect_args={"timeout": 8}
        )
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SET TRANSACTION READ ONLY"))
                row = (
                    (
                        await conn.execute(
                            text(
                                "SELECT 1 AS probe, current_database() AS database, "
                                "r.rolsuper, r.rolbypassrls FROM pg_roles r "
                                "WHERE r.rolname = current_user"
                            )
                        )
                    )
                    .mappings()
                    .one()
                )
                self.record("Database", "authentication and read-only query", "PASS", **dict(row))
                if row["rolsuper"] or row["rolbypassrls"]:
                    self.record(
                        "Database",
                        "application role isolation",
                        "WARN",
                        finding=(
                            "Configured role bypasses row-level security; "
                            "use a least-privilege application role."
                        ),
                    )
                ext = await conn.scalar(
                    text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
                )
                versions = list(
                    (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalars()
                )
                columns = (
                    await conn.execute(
                        text(
                            "SELECT table_name, column_name FROM information_schema.columns "
                            "WHERE table_name IN ('scan_embedding', 'agronomy_document_chunk')"
                        )
                    )
                ).all()
                pairs = set(columns)
                expected = {("scan_embedding", "embedding_text")}
                expected.update(
                    (table, column)
                    for table in ("scan_embedding", "agronomy_document_chunk")
                    for column in ("embedding_model", "gemini_embedding", "gemini_embedding_model")
                )
                missing = sorted(expected - pairs)
                self.record(
                    "Database",
                    "retrieval schema and migration",
                    "PASS" if ext and not missing else "FAIL",
                    pgvector=ext,
                    revisions=versions,
                    missing_columns=missing,
                )
        finally:
            await engine.dispose()

    async def redis(self):
        client = Redis.from_url(
            self.settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=6,
            socket_timeout=6,
        )
        key = f"agriverse:diagnostics:{self.run_id}"
        created = False
        try:
            assert await client.ping()
            self.record("Redis", "authenticated PING", "PASS")
            created = bool(await client.set(key, self.run_id, ex=120, nx=True))
            assert created, "Unique test key already exists"
            assert await client.get(key) == self.run_id
            assert 0 < await client.ttl(key) <= 120
            self.record("Redis", "SET/GET with TTL", "PASS")
        finally:
            try:
                if created:
                    await client.delete(key)
                    assert not await client.exists(key)
                    self.record("Redis", "temporary-key cleanup", "PASS")
            finally:
                await client.aclose()

    async def storage(self):
        s = self.settings
        session = aioboto3.Session()
        async with session.client(
            "s3",
            endpoint_url=s.s3_endpoint_url,
            aws_access_key_id=s.s3_access_key_id.get_secret_value(),
            aws_secret_access_key=s.s3_secret_access_key.get_secret_value(),
            region_name=s.s3_region,
            config=Config(connect_timeout=6, read_timeout=8, retries={"max_attempts": 0}),
        ) as client:
            await client.head_bucket(Bucket=s.s3_bucket)
            self.record("MinIO", "signed bucket authentication", "PASS", bucket=s.s3_bucket)
            keys = []
            try:
                for encrypted in (False, True):
                    key = f"diagnostics/{self.run_id}/{'encrypted' if encrypted else 'basic'}.jpg"
                    # Reserve this unique key for cleanup even if an upload times out.
                    keys.append(key)

                    async def operation(encrypted=encrypted, key=key):
                        extra = {"ServerSideEncryption": "AES256"} if encrypted else {}
                        await client.put_object(
                            Bucket=s.s3_bucket,
                            Key=key,
                            Body=self.image,
                            ContentType="image/jpeg",
                            **extra,
                        )
                        head = await client.head_object(Bucket=s.s3_bucket, Key=key)
                        data = await client.get_object(Bucket=s.s3_bucket, Key=key)
                        async with data["Body"] as stream:
                            actual = await stream.read()
                        assert actual == self.image and head["ContentLength"] == len(self.image)
                        if not encrypted and s.s3_public_endpoint_url:
                            from agriverse.services.storage import storage

                            url = await storage.presign_download(key)
                            async with httpx.AsyncClient(timeout=12, verify=self.trusted) as http:
                                public = await http.get(url)
                                public.raise_for_status()
                                assert public.content == self.image
                                self.record(
                                    "MinIO",
                                    "public signed download and byte integrity",
                                    "PASS",
                                    http_status=public.status_code,
                                    bytes_verified=len(public.content),
                                    fixture_encrypted=False,
                                )
                        return {
                            "bytes_verified": len(actual),
                            "encryption": head.get("ServerSideEncryption"),
                        }

                    await self.check(
                        "MinIO",
                        "application AES256 upload/read" if encrypted else "basic put/head/get",
                        operation,
                    )
                if s.s3_public_endpoint_url:
                    from agriverse.services.storage import storage

                    key = f"diagnostics/{self.run_id}/public.jpg"
                    keys.append(key)
                    put_url = await storage.presign_upload(key, "image/jpeg")
                    get_url = await storage.presign_download(key)
                    headers = storage.upload_headers("image/jpeg")
                    for trust_name, verify in (("application TLS trust", self.trusted),):

                        async def public_io(verify=verify):
                            async with httpx.AsyncClient(timeout=12, verify=verify) as http:
                                response = await http.put(
                                    put_url, content=self.image, headers=headers
                                )
                                response.raise_for_status()
                                result = await http.get(get_url)
                                result.raise_for_status()
                                assert result.content == self.image
                                return {
                                    "put_http_status": response.status_code,
                                    "get_http_status": result.status_code,
                                    "bytes_verified": len(result.content),
                                }

                        await self.check(
                            "MinIO", f"public presigned upload/download ({trust_name})", public_io
                        )

                    async def cors():
                        async with httpx.AsyncClient(timeout=12, verify=self.trusted) as http:
                            response = await http.options(
                                put_url,
                                headers={
                                    "Origin": s.web_origin,
                                    "Access-Control-Request-Method": "PUT",
                                    "Access-Control-Request-Headers": ",".join(
                                        header.lower() for header in headers
                                    ),
                                },
                            )
                            response.raise_for_status()
                            allowed = response.headers.get("access-control-allow-origin")
                            assert allowed in (s.web_origin, "*")
                            return {
                                "http_status": response.status_code,
                                "allowed_origin": allowed,
                                "allowed_methods": response.headers.get(
                                    "access-control-allow-methods"
                                ),
                            }

                    await self.check("MinIO", "browser upload CORS preflight (Windows trust)", cors)
            finally:
                for key in keys:

                    async def cleanup(key=key):
                        await client.delete_object(Bucket=s.s3_bucket, Key=key)
                        try:
                            await client.head_object(Bucket=s.s3_bucket, Key=key)
                        except Exception as exc:
                            if self.error(exc).get("http_status") == 404:
                                return {"object": key}
                            raise
                        raise AssertionError("Object remains after deletion")

                    await self.check("MinIO", "temporary-object cleanup", cleanup)

    async def weather(self):
        fields = "temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m"
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(
                self.settings.open_meteo_base_url.rstrip("/") + "/forecast",
                params={
                    "latitude": 22.5726,
                    "longitude": 88.3639,
                    "current": fields,
                    "hourly": fields,
                    "forecast_days": 3,
                    "timezone": "auto",
                },
            )
            response.raise_for_status()
            data = response.json()
        hourly = data["hourly"]
        assert len(hourly["time"]) == 72
        for name in fields.split(","):
            assert len(hourly[name]) == 72
            assert all(isinstance(x, (float, int)) and math.isfinite(x) for x in hourly[name])
            assert math.isfinite(data["current"][name])
        assert all(0 <= x <= 100 for x in hourly["relative_humidity_2m"])
        assert all(x >= 0 for x in hourly["precipitation"])
        self.record(
            "Open-Meteo",
            "live forecast response integrity",
            "PASS",
            http_status=response.status_code,
            hourly_points=72,
            timezone=data["timezone"],
            utc_offset_seconds=data["utc_offset_seconds"],
        )
        from agriverse.services.weather import OpenMeteoProvider

        forecast = await OpenMeteoProvider().current(22.5726, 88.3639)
        assert len(forecast.forecast) == 72
        self.record(
            "Open-Meteo",
            "application weather adapter",
            "PASS",
            hourly_points=len(forecast.forecast),
            source=forecast.source,
        )
        provider_offset = data["utc_offset_seconds"]
        expected_time = datetime.fromisoformat(data["current"]["time"])
        if expected_time.tzinfo is None:
            expected_time = expected_time.replace(
                tzinfo=timezone(timedelta(seconds=provider_offset))
            )
        drift = abs((forecast.current.observed_at - expected_time.astimezone(UTC)).total_seconds())
        self.record(
            "Open-Meteo",
            "application timezone integrity",
            "PASS" if drift <= 900 else "FAIL",
            provider_utc_offset_seconds=provider_offset,
            timestamp_drift_seconds=drift,
            normalized_to_utc=forecast.current.observed_at.utcoffset() == timedelta(0),
        )

    async def llm(self):
        from agriverse.services.ai import (
            FieldContext,
            LLMProvider,
            RetrievedContext,
            provider_client,
        )
        from agriverse.services.retrieval import EmbeddingService

        s = self.settings
        if s.openai_api_key.get_secret_value():
            client = provider_client("openai", s)
            try:

                async def infer():
                    result = await client.responses.create(
                        model=s.openai_agent_model,
                        input="Connectivity test. Reply OK.",
                        max_output_tokens=32,
                    )
                    assert result.output_text
                    return {"model": result.model, "output_nonempty": True}

                await self.check("OpenAI", "direct inference and key authentication", infer)

                async def embed():
                    result = await client.embeddings.create(
                        model=s.openai_embedding_model,
                        input=["AgriVerse connectivity test"],
                        dimensions=s.vector_dimension,
                    )
                    assert len(result.data[0].embedding) == s.vector_dimension
                    return {"dimensions": len(result.data[0].embedding), "model": result.model}

                await self.check("OpenAI", "direct retrieval embedding", embed)
            finally:
                await client.close()
        else:
            self.record("OpenAI", "configured", "NOT_CONFIGURED")
        if not s.gemini_api_key.get_secret_value():
            self.record("Gemini", "configured", "NOT_CONFIGURED")
            return
        isolated = s.model_copy(update={"openai_api_key": SecretStr("")})
        llm = LLMProvider(isolated)
        embeddings = EmbeddingService(isolated)
        try:

            async def answer():
                result, meta = await llm.answer(
                    question="Connectivity test only. Reply OK in one sentence.",
                    context={},
                    language="English",
                )
                assert result and meta["provider"] == "gemini"
                self.gemini_generation = meta
                return {
                    "provider": meta["provider"],
                    "model": meta["model"],
                    "structured_result_valid": True,
                }

            await self.check("Gemini", "application structured answer (isolated provider)", answer)

            async def gate():
                result = await llm.gate(self.image)
                return {
                    "is_plant_image": result.is_plant_image,
                    "is_diagnosable": result.is_diagnosable,
                    "model": result.metadata.get("model"),
                }

            await self.check("Gemini", "application image gate", gate)

            async def describe():
                result = await llm.describe_image(self.image)
                assert result
                return {"description_nonempty": True}

            await self.check("Gemini", "application retrieval image description", describe)

            async def diagnose():
                result, meta = await llm.diagnose(
                    self.image,
                    FieldContext(
                        field_id=uuid.UUID(int=1),
                        crop=None,
                        state="Synthetic",
                        district="Synthetic",
                        agro_climatic_zone="Synthetic",
                    ),
                    RetrievedContext(similar_cases=[], citations=[]),
                    "English",
                )
                assert result
                return {
                    "model": meta["model"],
                    "structured_result_valid": True,
                    "synthetic_image": True,
                }

            await self.check("Gemini", "application diagnosis schema", diagnose)

            async def rerank():
                indices = await llm.rank_documents(
                    "seed germination",
                    [
                        "Seeds require suitable moisture to germinate.",
                        "A storage connectivity diagnostic.",
                    ],
                )
                assert indices and indices[0] == 0
                return {"ranking_valid": True}

            await self.check("Gemini", "application retrieval reranking", rerank)
            for input_type in ("document", "query"):

                async def embed(input_type=input_type):
                    result = await embeddings._embed(
                        "gemini", ["AgriVerse connectivity test"], input_type
                    )
                    vector = result[0].vector
                    assert (
                        len(vector) == s.vector_dimension
                        and abs(sum(x * x for x in vector) - 1) < 1e-5
                    )
                    return {
                        "model": result[0].model,
                        "dimensions": len(vector),
                        "finite_normalized": True,
                    }

                await self.check("Gemini", f"application retrieval {input_type} embedding", embed)
        finally:
            await llm._client.close()
            await llm._gemini.close()
            await embeddings._client.close()
        if s.openai_api_key.get_secret_value():
            both = LLMProvider(s)
            try:

                async def fallback():
                    result, meta = await both.answer(
                        question="Connectivity test only. Reply OK.", context={}, language="English"
                    )
                    assert result
                    return {"selected_provider": meta["provider"], "model": meta["model"]}

                await self.check(
                    "LLM fallback", "application answer with both configured keys", fallback
                )
                combined = EmbeddingService(s)
                try:

                    async def embed_fallback():
                        result = await combined.embed_texts(
                            ["AgriVerse connectivity test"], input_type="query"
                        )
                        return {
                            "selected_provider": result[0].provider,
                            "dimensions": len(result[0].vector),
                        }

                    await self.check(
                        "LLM fallback",
                        "application retrieval with both configured keys",
                        embed_fallback,
                    )
                finally:
                    await combined._client.close()
            finally:
                await both._client.close()
                await both._gemini.close()

    def trace_payload(self, generation=False):
        from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
            ExportTraceServiceRequest,
        )

        request = ExportTraceServiceRequest()
        resource = request.resource_spans.add()
        attr = resource.resource.attributes.add(key="service.name")
        attr.value.string_value = "agriverse-diagnostics"
        attr = resource.resource.attributes.add(key="diagnostics.run_id")
        attr.value.string_value = self.run_id
        scope = resource.scope_spans.add()
        scope.scope.name = "agriverse.live-diagnostics"
        span = scope.spans.add(
            name="Gemini synthetic generation" if generation else "Live connectivity diagnostic",
            trace_id=secrets.token_bytes(16),
            span_id=secrets.token_bytes(8),
            kind=3,
            start_time_unix_nano=time.time_ns() - 1_000_000,
            end_time_unix_nano=time.time_ns(),
        )
        span.status.code = 1
        if generation:
            for key, value in {
                "gen_ai.system": "google",
                "gen_ai.request.model": self.settings.gemini_agent_model,
                "gen_ai.operation.name": "chat",
                "langfuse.observation.type": "generation",
                "langfuse.observation.model.name": self.settings.gemini_agent_model,
                "langfuse.observation.input": "Synthetic connectivity test; reply OK",
                "langfuse.observation.output": "Successful synthetic Gemini call",
            }.items():
                span.attributes.add(key=key).value.string_value = value
        return request, span.trace_id.hex()

    async def otel(self):
        from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import (
            ExportLogsServiceRequest,
            ExportLogsServiceResponse,
        )
        from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import (
            ExportMetricsServiceRequest,
            ExportMetricsServiceResponse,
        )
        from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
            ExportTraceServiceResponse,
        )

        base = (self.settings.otel_exporter_otlp_endpoint or "").rstrip("/")
        if not base:
            self.record("OTel", "configured", "NOT_CONFIGURED")
            return
        traces, _ = self.trace_payload()
        metrics = ExportMetricsServiceRequest()
        r = metrics.resource_metrics.add()
        r.resource.attributes.add(key="service.name").value.string_value = "agriverse-diagnostics"
        point = (
            r.scope_metrics.add()
            .metrics.add(name="agriverse_diagnostics_probe")
            .gauge.data_points.add(time_unix_nano=time.time_ns(), as_int=1)
        )
        point.attributes.add(key="run_id").value.string_value = self.run_id
        logs = ExportLogsServiceRequest()
        r = logs.resource_logs.add()
        r.resource.attributes.add(key="service.name").value.string_value = "agriverse-diagnostics"
        log = r.scope_logs.add().log_records.add(
            time_unix_nano=time.time_ns(), severity_number=9, severity_text="INFO"
        )
        log.body.string_value = "Synthetic AgriVerse live connectivity diagnostic " + self.run_id
        async with httpx.AsyncClient(timeout=12) as client:
            for signal, payload, response_type, rejected in (
                ("traces", traces, ExportTraceServiceResponse, "rejected_spans"),
                ("metrics", metrics, ExportMetricsServiceResponse, "rejected_data_points"),
                ("logs", logs, ExportLogsServiceResponse, "rejected_log_records"),
            ):

                async def export(
                    signal=signal, payload=payload, response_type=response_type, rejected=rejected
                ):
                    response = await client.post(
                        base + "/v1/" + signal,
                        content=payload.SerializeToString(),
                        headers={"Content-Type": "application/x-protobuf"},
                    )
                    response.raise_for_status()
                    parsed = response_type.FromString(response.content)
                    count = getattr(parsed.partial_success, rejected)
                    assert count == 0
                    return {
                        "http_status": response.status_code,
                        "rejected": count,
                        "scope": "collector acceptance; downstream persistence not queried",
                    }

                await self.check("OTel", f"OTLP {signal} export", export)

        async def sdk_export():
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import SpanExportResult

            def send():
                provider = TracerProvider(
                    resource=Resource.create({"service.name": "agriverse-diagnostics"}),
                    shutdown_on_exit=False,
                )
                exporter = OTLPSpanExporter(endpoint=base + "/v1/traces", timeout=12)
                try:
                    span = provider.get_tracer("agriverse.live-diagnostics").start_span(
                        "SDK exporter diagnostic", attributes={"diagnostics.run_id": self.run_id}
                    )
                    span.end()
                    result = exporter.export((span,))
                    assert result == SpanExportResult.SUCCESS
                    return {"sdk_export_result": result.name}
                finally:
                    exporter.shutdown()
                    provider.shutdown()

            return await asyncio.to_thread(send)

        await self.check("OTel", "application OTLP SDK trace exporter", sdk_export)

    async def langfuse(self):
        s = self.settings
        base = (s.langfuse_host or "").rstrip("/")
        if not base or not s.langfuse_public_key or not s.langfuse_secret_key.get_secret_value():
            self.record("Langfuse", "configured", "NOT_CONFIGURED")
            return
        for trust_name, verify in (("application TLS trust", self.trusted),):

            async def health(verify=verify):
                async with httpx.AsyncClient(timeout=12, verify=verify) as client:
                    response = await client.get(base + "/api/public/health")
                    response.raise_for_status()
                    return {
                        "http_status": response.status_code,
                        "version": response.json().get("version"),
                    }

            await self.check("Langfuse", f"health ({trust_name})", health)
        auth = httpx.BasicAuth(s.langfuse_public_key, s.langfuse_secret_key.get_secret_value())
        async with httpx.AsyncClient(timeout=15, verify=self.trusted, auth=auth) as client:

            async def projects():
                response = await client.get(base + "/api/public/projects")
                response.raise_for_status()
                data = response.json()
                assert isinstance(data.get("data"), list) and data["data"]
                return {
                    "http_status": response.status_code,
                    "accessible_projects": len(data["data"]),
                }

            result = await self.check("Langfuse", "key authentication (Windows trust)", projects)
            if result["status"] != "PASS":
                return
            if not self.gemini_generation:
                self.record(
                    "Langfuse",
                    "synthetic generation trace",
                    "SKIP",
                    reason="No successful Gemini inference available to trace",
                )
                return
            from agriverse.services.llm_tracing import flush_llm_traces

            assert await asyncio.to_thread(flush_llm_traces, s)
            trace_id = self.gemini_generation.get("trace_id")
            if not trace_id:
                self.record(
                    "Langfuse",
                    "automatic application LLM tracing",
                    "FAIL",
                    reason="Successful application inference returned no trace ID",
                )
                return

            async def readback():
                start = datetime.fromisoformat(self.started) - timedelta(minutes=2)
                for _attempt in range(10):
                    response = await client.get(
                        base + "/api/public/v2/observations",
                        params={
                            "traceId": trace_id,
                            "limit": 10,
                            "fields": "core,basic,usage",
                            "fromStartTime": start.isoformat(),
                            "toStartTime": datetime.now(UTC).isoformat(),
                        },
                    )
                    response.raise_for_status()
                    observations = [
                        row
                        for row in response.json().get("data", [])
                        if row.get("traceId") == trace_id
                    ]
                    if any(row.get("type") == "GENERATION" for row in observations):
                        return {
                            "http_status": response.status_code,
                            "trace_id": trace_id,
                            "observation_count": len(observations),
                            "types": [row.get("type") for row in observations],
                            "application_generated": True,
                        }
                    await asyncio.sleep(2)
                raise AssertionError("Application generation not found after trace flush")

            await self.check("Langfuse", "automatic application LLM tracing and readback", readback)

    async def oidc(self):
        s = self.settings
        for name in ("google", "microsoft"):
            if not getattr(s, name + "_client_id"):
                self.record("OIDC", name, "NOT_CONFIGURED")
            else:
                self.record(
                    "OIDC",
                    name,
                    "SKIP",
                    reason=(
                        "This diagnostic runner currently implements Keycloak flows; "
                        "use an interactive test for this provider."
                    ),
                )
        if not s.keycloak_issuer_url or not s.keycloak_client_id:
            self.record("OIDC", "Keycloak", "NOT_CONFIGURED")
            return
        from agriverse.routers.auth import create_oauth_clients

        oauth = create_oauth_clients(s)

        async def discovery_as_configured():
            metadata = await oauth.create_client("keycloak").load_server_metadata()
            assert metadata["issuer"] == s.keycloak_issuer_url.rstrip("/")
            return {"issuer_matches_configuration": True}

        await self.check(
            "OIDC", "Keycloak Authlib discovery as configured", discovery_as_configured
        )
        configured = s.keycloak_issuer_url.rstrip("/")
        async with httpx.AsyncClient(
            timeout=12, verify=self.trusted, follow_redirects=True
        ) as client:
            response = await client.get(configured + "/.well-known/openid-configuration")
            response.raise_for_status()
            data = response.json()
            issuer = data["issuer"]
            self.record(
                "OIDC",
                "Keycloak discovery (Windows trust, redirects)",
                "PASS",
                http_status=response.status_code,
                issuer=issuer,
                issuer_matches_configuration=issuer == configured,
                redirects=[r.status_code for r in response.history],
                pkce_s256="S256" in data.get("code_challenge_methods_supported", []),
            )

            async def jwks():
                response = await client.get(data["jwks_uri"])
                response.raise_for_status()
                keys = response.json()["keys"]
                assert keys and any(key.get("use") == "sig" for key in keys)
                return {"http_status": response.status_code, "signing_keys": len(keys)}

            await self.check("OIDC", "Keycloak signing keys (Windows trust)", jwks)

            async def authorization():
                verifier = secrets.token_urlsafe(48)
                challenge = (
                    base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
                    .rstrip(b"=")
                    .decode()
                )
                redirect = (
                    s.oauth_callback_base_url.rstrip("/") + "/auth/staff/oauth/keycloak/callback"
                )
                response = await client.get(
                    data["authorization_endpoint"],
                    params={
                        "client_id": s.keycloak_client_id,
                        "redirect_uri": redirect,
                        "response_type": "code",
                        "scope": "openid email profile",
                        "state": secrets.token_urlsafe(24),
                        "nonce": secrets.token_urlsafe(24),
                        "code_challenge": challenge,
                        "code_challenge_method": "S256",
                    },
                )
                response.raise_for_status()
                assert "kc-form-login" in response.text or 'name="username"' in response.text
                return {
                    "http_status": response.status_code,
                    "login_form_present": True,
                    "client_id": s.keycloak_client_id,
                    "redirect_uri": redirect,
                    "scope": (
                        "client/redirect acceptance only; no user authentication or token exchange"
                    ),
                }

            await self.check(
                "OIDC", "Keycloak authorization and callback registration", authorization
            )
        self.record(
            "OIDC",
            "Keycloak complete sign-in and session",
            "BLOCKED",
            reason=(
                "No interactive sign-in or token/session exchange was completed. "
                "Review the application, issuer and TLS checks before sign-in."
            ),
        )

    async def application(self):
        for name, url in (
            ("API", "http://localhost:8000/healthz"),
            ("Web", self.settings.web_origin.rstrip("/") + "/login"),
        ):

            async def probe(url=url):
                async with httpx.AsyncClient(timeout=30) as client:
                    response = await client.get(url)
                    response.raise_for_status()
                    return {"http_status": response.status_code}

            await self.check("Application", name + " live endpoint", probe)

    async def run(self):
        # Import providers before scheduling socket timeouts. Cold module imports
        # and OS certificate loading must not starve concurrent connection checks.
        for module in (
            "agriverse.services.ai",
            "agriverse.services.retrieval",
            "agriverse.services.weather",
            "agriverse.routers.auth",
        ):
            importlib.import_module(module)
        tasks = [
            ("Database", self.database),
            ("Redis", self.redis),
            ("MinIO", self.storage),
            ("Open-Meteo", self.weather),
            ("LLM", self.llm),
            ("Application", self.application),
        ]
        if self.args.otel:
            tasks.append(("OTel", self.otel))
        if self.args.oidc:
            tasks.append(("OIDC", self.oidc))

        async def group(name, fn):
            try:
                await fn()
            except Exception as exc:
                self.record(name, "diagnostic group error", "FAIL", **self.error(exc))

        await asyncio.gather(
            *(group(name, fn) for name, fn in tasks if not self.args.only or name in self.args.only)
        )
        if self.args.langfuse and (not self.args.only or "Langfuse" in self.args.only):
            await group("Langfuse", self.langfuse)
        print("REPORT " + str(self.output), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--otel", action="store_true", help="Authorize synthetic telemetry export")
    parser.add_argument(
        "--langfuse",
        action="store_true",
        help="Authorize project authentication and diagnostic trace ingestion",
    )
    parser.add_argument(
        "--oidc",
        action="store_true",
        help="Authorize configured identity-provider discovery/authorization checks",
    )
    parser.add_argument(
        "--only",
        nargs="+",
        choices=[
            "Database",
            "Redis",
            "MinIO",
            "Open-Meteo",
            "LLM",
            "Application",
            "OTel",
            "OIDC",
            "Langfuse",
        ],
        help="Limit diagnostics to named services; optional services still need their opt-in flags",
    )
    parser.add_argument(
        "--output",
        default=f"docs/reports/live-connectivity-{datetime.now(UTC):%Y-%m-%d-%H%M%S}.json",
    )
    asyncio.run(Diagnostics(parser.parse_args()).run())
