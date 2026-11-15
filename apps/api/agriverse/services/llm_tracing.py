"""Optional Langfuse export of LLM spans, independent of collector configuration.

Only task, provider, model, token counts, status and duration are exported. Images,
prompts, field data, answers, credentials and exception messages are excluded.
"""

import base64
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from typing import Any

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Span, Status, StatusCode

from agriverse.config import Settings
from agriverse.http import trusted_ca_file

logger = logging.getLogger(__name__)


@lru_cache(maxsize=8)
def _provider(
    host: str, public_key: str, secret_key: str, ca: str | None, environment: str
) -> TracerProvider:
    credentials = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()
    certificate_file = trusted_ca_file(ca)
    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": "agriverse-llm",
                "deployment.environment.name": environment,
            }
        )
    )
    provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(
                endpoint=host.rstrip("/") + "/api/public/otel/v1/traces",
                headers={
                    "Authorization": f"Basic {credentials}",
                    "x-langfuse-ingestion-version": "4",
                },
                certificate_file=certificate_file,
                timeout=5,
            )
        )
    )
    return provider


def tracing_provider(settings: Settings) -> TracerProvider | None:
    if not (
        settings.langfuse_host
        and settings.langfuse_public_key
        and settings.langfuse_secret_key.get_secret_value()
    ):
        return None
    try:
        return _provider(
            settings.langfuse_host,
            settings.langfuse_public_key,
            settings.langfuse_secret_key.get_secret_value(),
            settings.tls_ca_bundle,
            settings.app_env,
        )
    except Exception as exc:
        logger.warning("Optional LLM tracing unavailable (%s)", type(exc).__name__)
        return None


@contextmanager
def llm_span(settings: Settings, task: str, provider: str, model: str) -> Iterator[Span]:
    exporter = tracing_provider(settings)
    tracer = exporter.get_tracer(__name__) if exporter else trace.get_tracer(__name__)
    with tracer.start_as_current_span(
        f"llm.{task}",
        attributes={
            "gen_ai.system": "openai" if provider == "openai" else "google",
            "gen_ai.request.model": model,
            "gen_ai.operation.name": "embeddings" if task == "embedding" else "chat",
            "langfuse.observation.type": "span" if task == "embedding" else "generation",
            "langfuse.observation.model.name": model,
            "agriverse.llm.task": task,
        },
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        try:
            yield span
        except BaseException as exc:
            span.set_status(Status(StatusCode.ERROR))
            span.set_attribute("error.type", type(exc).__name__)
            raise


def record_usage(span: Span, metadata: dict[str, Any]) -> None:
    context = span.get_span_context()
    if context.is_valid:
        metadata["trace_id"] = f"{context.trace_id:032x}"
    usage = metadata.get("usage", {})
    for attribute, names in (
        ("gen_ai.usage.input_tokens", ("input_tokens", "prompt_tokens")),
        ("gen_ai.usage.output_tokens", ("output_tokens", "completion_tokens")),
    ):
        for name in names:
            value = usage.get(name)
            if isinstance(value, int):
                span.set_attribute(attribute, value)
                break


def flush_llm_traces(settings: Settings) -> bool:
    provider = tracing_provider(settings)
    return provider.force_flush(timeout_millis=5000) if provider else True
