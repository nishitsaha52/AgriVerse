import ssl
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import APIConnectionError
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from agriverse.config import Settings
from agriverse.http import ssl_context, trusted_ca_file
from agriverse.services import llm_tracing
from agriverse.services.ai import AIProviderError, AnswerText, LLMProvider


def test_system_trust_keeps_certificate_and_hostname_verification_enabled():
    context = ssl_context()
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname
    assert context.get_ca_certs()
    exported = ssl.create_default_context(cafile=trusted_ca_file())
    assert exported.verify_mode == ssl.CERT_REQUIRED and exported.check_hostname


def test_incomplete_langfuse_configuration_does_not_create_exporter(monkeypatch):
    monkeypatch.setattr(llm_tracing, "_provider", lambda *args: pytest.fail("unexpected exporter"))
    assert llm_tracing.tracing_provider(Settings(_env_file=None, langfuse_host="")) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [False, True])
async def test_llm_calls_export_metadata_without_prompt_answer_or_exception_text(
    monkeypatch, failure
):
    exporter = InMemorySpanExporter()
    provider = TracerProvider(shutdown_on_exit=False)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(llm_tracing, "tracing_provider", lambda settings: provider)
    llm = LLMProvider(Settings(_env_file=None, openai_api_key="test-only", gemini_api_key=""))
    if failure:
        llm._client.responses.parse = AsyncMock(
            side_effect=APIConnectionError(
                message="private-error-message",
                request=httpx.Request("POST", "https://example.com"),
            )
        )
    else:
        llm._client.responses.parse = AsyncMock(
            return_value=SimpleNamespace(
                output=[],
                output_parsed=AnswerText(answer="private-answer"),
                model="test-model",
                usage=SimpleNamespace(model_dump=lambda: {"input_tokens": 4, "output_tokens": 2}),
            )
        )
    try:
        if failure:
            with pytest.raises(AIProviderError):
                await llm.answer(question="private-question", context={}, language="en")
        else:
            answer, metadata = await llm.answer(
                question="private-question", context={}, language="en"
            )
            assert answer == "private-answer"
            assert len(metadata["trace_id"]) == 32
        spans = exporter.get_finished_spans()
        assert len(spans) == 1 and spans[0].name == "llm.agent"
        span = spans[0]
        assert span.attributes["langfuse.observation.type"] == "generation"
        assert not span.events
        assert not any(
            value in str(span.attributes)
            for value in (
                "private-question",
                "private-answer",
                "private-error-message",
                "test-only",
            )
        )
        if failure:
            assert span.status.status_code == StatusCode.ERROR
            assert span.attributes["error.type"] == "APIConnectionError"
        else:
            assert span.attributes["gen_ai.usage.input_tokens"] == 4
            assert span.attributes["gen_ai.usage.output_tokens"] == 2
    finally:
        await llm._client.close()
        await llm._gemini.close()
        provider.shutdown()
