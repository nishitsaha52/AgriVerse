import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import APIConnectionError

from agriverse.config import Settings
from agriverse.schemas import DiagnosisResult
from agriverse.services import ai, retrieval
from agriverse.services.ai import (
    AIProviderError,
    AIRefusalError,
    AnswerText,
    DocumentRanking,
    FieldContext,
    GateResult,
    ImageDescription,
    LLMProvider,
    RetrievedContext,
)
from agriverse.services.retrieval import EmbeddedText, EmbeddingService, _vector_literal
from tests.fakes import FakeSession


def configured(**kwargs):
    return Settings(
        _env_file=None,
        openai_api_key="test-openai",
        gemini_api_key="test-gemini",
        vector_dimension=2,
        **kwargs,
    )


def unavailable():
    return APIConnectionError(request=httpx.Request("POST", "https://api.openai.com/v1/responses"))


def gemini_result(parsed):
    return SimpleNamespace(
        id="gemini-response",
        model="gemini-test",
        usage=None,
        choices=[SimpleNamespace(message=SimpleNamespace(parsed=parsed, refusal=None))],
    )


@pytest.mark.parametrize("task", ["gate", "diagnose", "answer", "describe_image", "rank_documents"])
async def test_all_generation_tasks_fall_back_to_gemini(task):
    provider = LLMProvider(configured())
    primary = AsyncMock(side_effect=unavailable())
    outputs = {
        "gate": GateResult(is_plant_image=False, is_diagnosable=False),
        "diagnose": DiagnosisResult(image_is_diagnosable=False, rejection_reason="blurred"),
        "answer": AnswerText(answer="Inspect the field."),
        "describe_image": ImageDescription(description="Green leaf with round brown lesions."),
        "rank_documents": DocumentRanking(indices=[1, 0]),
    }
    fallback = AsyncMock(return_value=gemini_result(outputs[task]))
    provider._client = SimpleNamespace(responses=SimpleNamespace(parse=primary))
    provider._gemini = SimpleNamespace(
        beta=SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(parse=fallback)),
        )
    )
    if task == "gate":
        result = await provider.gate(b"image")
        assert result.metadata["provider"] == "gemini"
    elif task == "diagnose":
        _, metadata = await provider.diagnose(
            b"image",
            FieldContext(
                field_id=uuid.uuid4(),
                crop="rice",
                state="KA",
                district="Mysuru",
                agro_climatic_zone="zone",
            ),
            RetrievedContext(similar_cases=[], citations=[]),
            "en",
        )
        assert metadata["provider"] == "gemini"
    elif task == "answer":
        answer, metadata = await provider.answer(question="What next?", context={}, language="en")
        assert answer == "Inspect the field." and metadata["provider"] == "gemini"
    elif task == "describe_image":
        assert "lesions" in await provider.describe_image(b"image")
    else:
        assert await provider.rank_documents("seed", ["unrelated", "clean seed"]) == [1, 0]
    primary.assert_awaited_once()
    fallback.assert_awaited_once()


async def test_primary_success_does_not_call_fallback():
    provider = LLMProvider(configured())
    provider._client.responses.parse = AsyncMock(
        return_value=SimpleNamespace(
            output_parsed=AnswerText(answer="Primary answer"),
            output=[SimpleNamespace(type="reasoning", content=None)],
            id="r1",
            model="primary",
            usage=None,
        )
    )
    provider._gemini.beta.chat.completions.parse = AsyncMock()
    answer, metadata = await provider.answer(question="Question", context={}, language="en")
    assert answer == "Primary answer" and metadata["provider"] == "openai"
    provider._gemini.beta.chat.completions.parse.assert_not_called()


async def test_safety_refusal_does_not_trigger_fallback():
    provider = LLMProvider(configured())
    provider._client.responses.parse = AsyncMock(
        return_value=SimpleNamespace(
            output_parsed=None,
            output=[SimpleNamespace(content=[SimpleNamespace(type="refusal")])],
        )
    )
    provider._gemini.beta.chat.completions.parse = AsyncMock()
    with pytest.raises(AIRefusalError):
        await provider.gate(b"image")
    provider._gemini.beta.chat.completions.parse.assert_not_called()


async def test_missing_keys_do_not_send_requests():
    provider = LLMProvider(Settings(_env_file=None))
    provider._client.responses.parse = AsyncMock()
    with pytest.raises(AIProviderError, match="OPENAI_API_KEY"):
        await provider.gate(b"image")
    provider._client.responses.parse.assert_not_called()


def test_provider_keys_always_use_direct_endpoints(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "http://former-gateway:4000/v1")
    provider = LLMProvider(configured())
    assert str(provider._client.base_url) == "https://api.openai.com/v1/"
    assert (
        str(provider._gemini.base_url) == "https://generativelanguage.googleapis.com/v1beta/openai/"
    )
    assert provider._client.max_retries == 0


async def test_embedding_fallback_uses_native_gemini_parameters(monkeypatch):
    service = EmbeddingService(configured())
    service._client.embeddings.create = AsyncMock(side_effect=unavailable())
    real_client = httpx.AsyncClient

    def respond(request):
        assert request.headers["x-goog-api-key"] == "test-gemini"
        assert request.url.host == "generativelanguage.googleapis.com"
        body = json.loads(request.content)
        assert body["requests"][0]["outputDimensionality"] == 2
        assert body["requests"][0]["taskType"] == "RETRIEVAL_QUERY"
        return httpx.Response(200, json={"embeddings": [{"values": [3.0, 4.0]}]})

    monkeypatch.setattr(
        retrieval.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(respond),
            **kwargs,
        ),
    )
    result = (await service.embed_texts(["leaf symptoms"], input_type="query"))[0]
    assert result.provider == "gemini"
    assert result.model == "gemini-embedding-001"
    assert result.vector == [0.6, 0.8]


async def test_ingestion_keeps_both_embedding_spaces_separate(monkeypatch):
    service = EmbeddingService(configured())

    async def embed(provider, texts, input_type):
        return [
            EmbeddedText(
                [0.6, 0.8] if provider == "openai" else [0.8, 0.6],
                provider,
                provider + "-model",
                text,
            )
            for text in texts
        ]

    monkeypatch.setattr(service, "_embed", embed)
    result = (await service.embed_documents(["clean seed"]))[0]
    assert result.preferred.provider == "openai"
    assert result.columns() == {
        "embedding": [0.6, 0.8],
        "embedding_model": "openai-model",
        "gemini_embedding": [0.8, 0.6],
        "gemini_embedding_model": "gemini-model",
    }


async def test_ingestion_continues_with_gemini_when_primary_is_down(monkeypatch):
    service = EmbeddingService(configured())

    async def embed(provider, texts, input_type):
        if provider == "openai":
            raise unavailable()
        return [EmbeddedText([0.6, 0.8], "gemini", "gemini-model", value) for value in texts]

    monkeypatch.setattr(service, "_embed", embed)
    result = (await service.embed_documents(["clean seed"]))[0]
    assert result.preferred.provider == "gemini"
    assert "embedding" not in result.columns()
    assert "gemini_embedding" in result.columns()


@pytest.mark.parametrize("vector", [[1.0], [0.0, 0.0], [float("nan"), 1.0]])
async def test_invalid_embeddings_are_rejected(vector):
    service = EmbeddingService(
        Settings(_env_file=None, openai_api_key="test-openai", vector_dimension=2)
    )
    service._client.embeddings.create = AsyncMock(
        return_value=SimpleNamespace(
            data=[SimpleNamespace(index=0, embedding=vector)],
        )
    )
    with pytest.raises(AIProviderError):
        await service.embed_texts(["rice"])


async def test_search_uses_matching_provider_model_and_tenant():
    class RecordingSession(FakeSession):
        async def execute(self, statement, parameters=None):
            self.statement = str(statement)
            self.parameters = parameters
            return await super().execute(statement, parameters)

    db = RecordingSession()
    vector = EmbeddedText([0.6, 0.8], "gemini", "gemini-model")
    org = uuid.uuid4()
    await retrieval.search_similar_scans(db, organization_id=org, embedding=vector)
    assert "gemini_embedding_model = :embedding_model" in db.statement
    assert "confirmed_dx IS NOT NULL" in db.statement
    assert db.parameters["organization_id"] == org
    assert db.parameters["embedding_model"] == "gemini-model"
    await retrieval.search_documents(db, query_embedding=vector, agro_climatic_zone="zone")
    assert "c.gemini_embedding_model = :embedding_model" in db.statement
    assert "d.applicable_regions" in db.statement
    assert db.parameters["embedding_model"] == "gemini-model"


async def test_bad_ranking_cannot_select_outside_candidates(monkeypatch):
    provider = LLMProvider(configured())
    monkeypatch.setattr(
        provider, "_generate", AsyncMock(return_value=(DocumentRanking(indices=[4]), {}))
    )
    with pytest.raises(AIProviderError, match="indices"):
        await provider.rank_documents("seed", ["one document"])
    monkeypatch.setattr(
        ai.vision_provider, "rank_documents", AsyncMock(side_effect=AIProviderError())
    )
    service = EmbeddingService(configured())
    rows = [{"content": "seed advice"}]
    assert await service.rerank("seed", rows, limit=1) == rows


def test_vector_literal_rejects_nonfinite_values():
    with pytest.raises(ValueError):
        _vector_literal([float("inf")])
