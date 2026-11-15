import asyncio
import math
import uuid
from dataclasses import dataclass
from typing import Any

import httpx
import structlog
from openai import OpenAIError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agriverse.config import Settings, get_settings
from agriverse.http import ssl_context
from agriverse.schemas import Citation
from agriverse.services.ai import AIProviderError, Provider, provider_client, vision_provider
from agriverse.services.llm_tracing import llm_span

logger = structlog.get_logger()


@dataclass(frozen=True)
class EmbeddedText:
    vector: list[float]
    provider: Provider
    model: str
    text: str = ""


@dataclass(frozen=True)
class StoredEmbeddings:
    text: str
    openai: EmbeddedText | None = None
    gemini: EmbeddedText | None = None

    @property
    def preferred(self) -> EmbeddedText:
        result = self.openai or self.gemini
        if result is None:
            raise AIProviderError("No retrieval embeddings are available")
        return result

    def columns(self) -> dict[str, Any]:
        values: dict[str, Any] = {}
        if self.openai is not None:
            values.update(embedding=self.openai.vector, embedding_model=self.openai.model)
        if self.gemini is not None:
            values.update(
                gemini_embedding=self.gemini.vector, gemini_embedding_model=self.gemini.model
            )
        return values


class EmbeddingService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = provider_client("openai", self.settings)

    def _providers(self) -> list[Provider]:
        providers: list[Provider] = []
        if self.settings.openai_api_key.get_secret_value():
            providers.append("openai")
        if self.settings.gemini_api_key.get_secret_value():
            providers.append("gemini")
        return providers

    def _normalize(self, vector: list[float]) -> list[float]:
        if len(vector) != self.settings.vector_dimension or not all(map(math.isfinite, vector)):
            raise AIProviderError("Embedding provider returned an invalid vector")
        length = math.sqrt(sum(value * value for value in vector))
        if length == 0 or not math.isfinite(length):
            raise AIProviderError("Embedding provider returned a vector with invalid magnitude")
        return [value / length for value in vector]

    async def _embed(
        self,
        provider: Provider,
        texts: list[str],
        input_type: str,
    ) -> list[EmbeddedText]:
        model = str(getattr(self.settings, f"{provider}_embedding_model"))
        with llm_span(self.settings, "embedding", provider, model):
            return await self._embed_provider(provider, texts, input_type)

    async def _embed_provider(
        self,
        provider: Provider,
        texts: list[str],
        input_type: str,
    ) -> list[EmbeddedText]:
        model = str(getattr(self.settings, f"{provider}_embedding_model"))
        vectors: list[list[float]] = []
        for offset in range(0, len(texts), 64):
            batch = texts[offset : offset + 64]
            if provider == "openai":
                response = await self._client.embeddings.create(
                    model=model,
                    input=batch,
                    dimensions=self.settings.vector_dimension,
                    encoding_format="float",
                )
                items = sorted(response.data, key=lambda item: item.index)
                if [item.index for item in items] != list(range(len(batch))):
                    raise AIProviderError("Embedding provider returned incomplete results")
                vectors.extend(item.embedding for item in items)
            else:
                async with httpx.AsyncClient(
                    timeout=self.settings.ai_timeout_seconds,
                    verify=ssl_context(self.settings.tls_ca_bundle),
                ) as client:
                    response_http = await client.post(
                        f"https://generativelanguage.googleapis.com/v1beta/models/{model}"
                        ":batchEmbedContents",
                        headers={"x-goog-api-key": self.settings.gemini_api_key.get_secret_value()},
                        json={
                            "requests": [
                                {
                                    "model": f"models/{model}",
                                    "content": {"parts": [{"text": value}]},
                                    "taskType": (
                                        "RETRIEVAL_QUERY"
                                        if input_type == "query"
                                        else "RETRIEVAL_DOCUMENT"
                                    ),
                                    "outputDimensionality": self.settings.vector_dimension,
                                }
                                for value in batch
                            ]
                        },
                    )
                    response_http.raise_for_status()
                    try:
                        results = response_http.json()["embeddings"]
                        if len(results) != len(batch):
                            raise AIProviderError("Embedding provider returned incomplete results")
                        vectors.extend(
                            [float(value) for value in item["values"]] for item in results
                        )
                    except (KeyError, TypeError, ValueError) as exc:
                        raise AIProviderError("Gemini returned invalid embeddings") from exc
        return [
            EmbeddedText(self._normalize(vector), provider, model, original)
            for vector, original in zip(vectors, texts, strict=True)
        ]

    async def embed_texts(
        self,
        texts: list[str],
        *,
        input_type: str = "document",
        provider: Provider | None = None,
    ) -> list[EmbeddedText]:
        if not texts:
            return []
        for candidate in [provider] if provider else self._providers():
            if candidate not in self._providers():
                continue
            try:
                return await self._embed(candidate, texts, input_type)
            except (OpenAIError, httpx.HTTPError, AIProviderError) as exc:
                logger.warning(
                    "embedding_provider_failed", provider=candidate, error=type(exc).__name__
                )
        raise AIProviderError("Configured embedding providers are unavailable")

    async def embed_documents(self, texts: list[str]) -> list[StoredEmbeddings]:
        if not texts:
            return []
        providers = self._providers()
        # Keep a separate fallback corpus ready when both keys are configured.
        # Never write one provider's vector into the other provider's column.
        results = await asyncio.gather(
            *(self.embed_texts(texts, provider=provider) for provider in providers),
            return_exceptions=True,
        )
        successful: dict[Provider, list[EmbeddedText]] = {}
        for provider, result in zip(providers, results, strict=True):
            if isinstance(result, AIProviderError):
                continue
            if isinstance(result, BaseException):
                raise result
            successful[provider] = result
        if not successful:
            raise AIProviderError("No retrieval provider could embed the documents")
        return [
            StoredEmbeddings(
                original,
                successful["openai"][index] if "openai" in successful else None,
                successful["gemini"][index] if "gemini" in successful else None,
            )
            for index, original in enumerate(texts)
        ]

    async def embed_image(self, image: bytes) -> StoredEmbeddings:
        description = await vision_provider.describe_image(image)
        return (await self.embed_documents([description]))[0]

    async def rerank(
        self,
        query: str,
        rows: list[dict[str, Any]],
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        if not rows:
            return []
        try:
            indices = await vision_provider.rank_documents(
                query,
                [str(row["content"])[:4000] for row in rows],
            )
            ranked = [rows[index] for index in indices]
            ranked.extend(row for index, row in enumerate(rows) if index not in indices)
            return ranked[:limit]
        except AIProviderError:
            logger.warning("rerank_unavailable")
            return rows[:limit]


def _vector_literal(embedding: list[float]) -> str:
    if not embedding or not all(map(math.isfinite, embedding)):
        raise ValueError("A nonempty finite embedding is required")
    return "[" + ",".join(f"{value:.9g}" for value in embedding) + "]"


def _columns(embedding: EmbeddedText) -> tuple[str, str]:
    if embedding.provider == "openai":
        return "embedding", "embedding_model"
    if embedding.provider == "gemini":
        return "gemini_embedding", "gemini_embedding_model"
    raise ValueError("Unknown embedding provider")


async def _fallback_query(embedding: EmbeddedText) -> EmbeddedText | None:
    if (
        embedding.provider == "openai"
        and embedding.text
        and embedding_service.settings.gemini_api_key.get_secret_value()
    ):
        try:
            return (
                await embedding_service.embed_texts(
                    [embedding.text],
                    input_type="query",
                    provider="gemini",
                )
            )[0]
        except AIProviderError:
            logger.warning("fallback_retrieval_unavailable")
    return None


async def search_similar_scans(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    embedding: EmbeddedText,
    limit: int = 5,
) -> list[dict[str, Any]]:
    column, model_column = _columns(embedding)
    rows = (
        await db.execute(
            text(
                f"SELECT scan_id, confirmed_dx, "  # noqa: S608 -- fixed column allowlist
                f"1 - ({column} <=> CAST(:embedding AS vector)) AS similarity "
                f"FROM scan_embedding WHERE organization_id = :organization_id "
                f"AND confirmed_dx IS NOT NULL AND {model_column} = :embedding_model "
                f"AND {column} IS NOT NULL "
                f"ORDER BY {column} <=> CAST(:embedding AS vector) LIMIT :candidate_limit"
            ),
            {
                "embedding": _vector_literal(embedding.vector),
                "embedding_model": embedding.model,
                "organization_id": organization_id,
                "candidate_limit": limit * 20,
            },
        )
    ).mappings()
    candidates = [dict(row) for row in list(rows)[:limit]]
    if not candidates and (fallback := await _fallback_query(embedding)) is not None:
        return await search_similar_scans(
            db,
            organization_id=organization_id,
            embedding=fallback,
            limit=limit,
        )
    return candidates


async def search_documents(
    db: AsyncSession,
    *,
    query_embedding: EmbeddedText,
    agro_climatic_zone: str,
    query: str | None = None,
    maximum_tier: int = 3,
    limit: int = 5,
) -> list[dict[str, Any]]:
    column, model_column = _columns(query_embedding)
    rows = (
        await db.execute(
            text(
                "SELECT c.id AS chunk_id, c.content, c.page_number, c.section, "  # noqa: S608
                "d.title, d.publisher, d.licence, d.source_url, d.tier, "
                f"1 - (c.{column} <=> CAST(:embedding AS vector)) AS similarity "
                "FROM agronomy_document_chunk c "
                "JOIN agronomy_document d ON d.id = c.document_id "
                "WHERE d.tier <= :maximum_tier "
                f"AND c.{model_column} = :embedding_model AND c.{column} IS NOT NULL "
                "AND (d.applicable_regions ? 'national' "
                "OR d.applicable_regions ? :agro_climatic_zone) "
                f"ORDER BY c.{column} <=> CAST(:embedding AS vector) LIMIT :candidate_limit"
            ),
            {
                "embedding": _vector_literal(query_embedding.vector),
                "embedding_model": query_embedding.model,
                "maximum_tier": maximum_tier,
                "agro_climatic_zone": agro_climatic_zone,
                "candidate_limit": limit * 10,
            },
        )
    ).mappings()
    candidates = [dict(row) for row in rows]
    if not candidates and (fallback := await _fallback_query(query_embedding)) is not None:
        return await search_documents(
            db,
            query_embedding=fallback,
            agro_climatic_zone=agro_climatic_zone,
            query=query,
            maximum_tier=maximum_tier,
            limit=limit,
        )
    if query:
        return await embedding_service.rerank(query, candidates, limit=limit)
    return candidates[:limit]


def citations_from_document_rows(rows: list[dict[str, Any]]) -> list[Citation]:
    return [
        Citation(
            chunk_id=row["chunk_id"],
            publisher=row["publisher"],
            title=row["title"],
            page=row["page_number"],
            section=row["section"],
            licence=row["licence"],
            source_url=row["source_url"],
            tier=row["tier"],
        )
        for row in rows
    ]


embedding_service = EmbeddingService()
