import asyncio
import functools
import importlib
import logging
import time
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI
from opentelemetry import metrics, trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.metrics import Counter, Histogram, Meter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from sqlalchemy.engine import Engine

from agriverse.config import get_settings
from agriverse.http import trusted_ca_file

settings = get_settings()

_configured = False
_meter: Meter | None = None
_task_duration_histogram: Histogram | None = None
_task_counter: Counter | None = None


def _configure_observability(
    app: FastAPI | None = None,
    engine: Engine | None = None,
    redis_client: Any = None,
    service_name: str | None = None,
) -> None:
    """
    Unified OpenTelemetry configuration for AgriVerse.
    Exports Traces -> Tempo, Metrics -> Prometheus, Logs -> Loki via OTel Collector (:4318).
    """
    global _configured, _meter, _task_duration_histogram, _task_counter
    if _configured:
        return

    base_endpoint = (settings.otel_exporter_otlp_endpoint or "").strip().rstrip("/")
    resolved_service_name = service_name or settings.otel_service_name or "agriverse-api"
    certificate_file = trusted_ca_file(settings.tls_ca_bundle)

    res = Resource.create(
        {
            SERVICE_NAME: resolved_service_name,
            SERVICE_VERSION: "0.1.0",
            "environment": settings.app_env,
        }
    )

    # 1. ── TRACES (Tempo) ───────────────────────────────────────────────────
    tracer_provider = TracerProvider(resource=res)
    trace_endpoint = (
        f"{base_endpoint}/v1/traces" if not base_endpoint.endswith("/v1/traces") else base_endpoint
    )
    tracer_provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(endpoint=trace_endpoint, certificate_file=certificate_file)
        )
    )
    trace.set_tracer_provider(tracer_provider)

    # 2. ── METRICS (Prometheus via OTel Collector :8889) ───────────────────
    metric_endpoint = (
        f"{base_endpoint}/v1/metrics"
        if not base_endpoint.endswith("/v1/metrics")
        else base_endpoint
    )
    metric_reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=metric_endpoint, certificate_file=certificate_file),
        export_interval_millis=2000,
    )
    meter_provider = MeterProvider(resource=res, metric_readers=[metric_reader])
    metrics.set_meter_provider(meter_provider)
    _meter = metrics.get_meter(resolved_service_name)

    _task_duration_histogram = _meter.create_histogram(
        name="worker_task_duration_seconds",
        description="Duration of background worker tasks",
        unit="s",
    )
    _task_counter = _meter.create_counter(
        name="worker_tasks_total",
        description="Total background worker tasks executed",
        unit="1",
    )

    # 3. ── LOGS (Loki via OTel Collector /otlp) ─────────────────────────────
    log_endpoint = (
        f"{base_endpoint}/v1/logs" if not base_endpoint.endswith("/v1/logs") else base_endpoint
    )
    logger_provider = LoggerProvider(resource=res)
    logger_provider.add_log_record_processor(
        BatchLogRecordProcessor(
            OTLPLogExporter(endpoint=log_endpoint, certificate_file=certificate_file)
        )
    )
    set_logger_provider(logger_provider)

    try:
        logging_instrumentation = importlib.import_module("opentelemetry.instrumentation.logging")
        logging_instrumentation.LoggingInstrumentor().instrument(set_logging_format=True)
    except Exception:
        pass

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(LoggingHandler(logger_provider=logger_provider))

    # 4. ── INSTRUMENTATIONS ─────────────────────────────────────────────────
    if app:
        FastAPIInstrumentor.instrument_app(
            app, tracer_provider=tracer_provider, meter_provider=meter_provider
        )

    HTTPXClientInstrumentor().instrument(tracer_provider=tracer_provider)

    if engine:
        try:
            from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

            SQLAlchemyInstrumentor().instrument(engine=engine, tracer_provider=tracer_provider)
        except Exception:
            pass

    if redis_client:
        try:
            from opentelemetry.instrumentation.redis import RedisInstrumentor

            RedisInstrumentor().instrument(tracer_provider=tracer_provider)
        except Exception:
            pass

    _configured = True
    logging.info(f"Observability active for service '{resolved_service_name}' -> {base_endpoint}")


def configure_observability(
    app: FastAPI | None = None,
    engine: Engine | None = None,
    redis_client: Any | None = None,
    service_name: str | None = None,
) -> None:
    """Enable optional telemetry only when configured; keep API startup independent."""
    if not (settings.otel_exporter_otlp_endpoint or "").strip():
        return
    try:
        _configure_observability(app, engine, redis_client, service_name)
    except Exception as exc:
        logging.getLogger(__name__).warning(
            "Optional telemetry setup failed (%s); continuing application startup",
            type(exc).__name__,
        )


def track_worker_task(task_name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator for ARQ tasks and worker routines to record spans and metrics."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            tracer = trace.get_tracer(__name__)
            start_time = time.perf_counter()
            status = "success"
            with tracer.start_as_current_span(f"worker_task:{task_name}") as span:
                span.set_attribute("task.name", task_name)
                try:
                    return await func(*args, **kwargs)
                except Exception as exc:
                    status = "error"
                    span.record_exception(exc)
                    raise
                finally:
                    duration = time.perf_counter() - start_time
                    if _task_duration_histogram:
                        _task_duration_histogram.record(
                            duration, {"task.name": task_name, "status": status}
                        )
                    if _task_counter:
                        _task_counter.add(1, {"task.name": task_name, "status": status})

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            tracer = trace.get_tracer(__name__)
            start_time = time.perf_counter()
            status = "success"
            with tracer.start_as_current_span(f"worker_task:{task_name}") as span:
                span.set_attribute("task.name", task_name)
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    status = "error"
                    span.record_exception(exc)
                    raise
                finally:
                    duration = time.perf_counter() - start_time
                    if _task_duration_histogram:
                        _task_duration_histogram.record(
                            duration, {"task.name": task_name, "status": status}
                        )
                    if _task_counter:
                        _task_counter.add(1, {"task.name": task_name, "status": status})

        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper

    return decorator
