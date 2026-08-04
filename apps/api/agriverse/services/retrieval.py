import uuid
from io import BytesIO
from typing import Any, cast

import voyageai
from PIL import Image
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agriverse.config import get_settings
from agriverse.schemas import Citation

settings = get_settings()


class EmbeddingService:
    def __init__(self) -> None:
        self._client = voyageai.AsyncClient(api_key=settings.voyage_api_key.get_secret_value())

    async def embed_image(self, image: bytes, *, input_type: str = "document") -> list[float]:
        with Image.open(BytesIO(image)) as decoded:
            inputs: Any = [[decoded.copy()]]
            result = await self._client.multimodal_embed(
                inputs=inputs,
                model=settings.voyage_image_model,
                input_type=input_type,
            )
        vector = result.embeddings[0]
        if len(vector) != settings.vector_dimension:
            raise RuntimeError("Unexpected image embedding dimension")
        return vector

    async def embed_texts(
        self, texts: list[str], *, input_type: str = "document"
    ) -> list[list[float]]:
        result = await self._client.embed(
            texts,
            model=settings.voyage_text_model,
            input_type=input_type,
            output_dimension=settings.vector_dimension,
        )
        return cast(list[list[float]], result.embeddings)

    async def rerank(
        self,
        query: str,
        rows: list[dict[str, Any]],
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        if not rows:
            return []
        result: Any = await self._client.rerank(
            query=query,
            documents=[str(row["content"]) for row in rows],
            model=settings.voyage_rerank_model,
            top_k=limit,
        )
        return [rows[int(item.index)] for item in result.results]


def _vector_literal(embedding: list[float]) -> str:
    return "[" + ",".join(f"{value:.9g}" for value in embedding) + "]"


async def search_similar_scans(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    embedding: list[float],
    limit: int = 5,
) -> list[dict[str, Any]]:
    candidate_limit = limit * 20
    rows = (
        await db.execute(
            text(
                """
                SELECT scan_id, confirmed_dx,
                       1 - (embedding <=> CAST(:embedding AS vector)) AS similarity
                FROM scan_embedding
                WHERE organization_id = :organization_id
                  AND confirmed_dx IS NOT NULL
                ORDER BY embedding <=> CAST(:embedding AS vector)
                LIMIT :candidate_limit
                """
            ),
            {
                "embedding": _vector_literal(embedding),
                "organization_id": organization_id,
                "candidate_limit": candidate_limit,
            },
        )
    ).mappings()
    return [dict(row) for row in list(rows)[:limit]]


async def search_documents(
    db: AsyncSession,
    *,
    query_embedding: list[float],
    agro_climatic_zone: str,
    query: str | None = None,
    maximum_tier: int = 3,
    limit: int = 5,
) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            text(
                """
                SELECT c.id AS chunk_id, c.content, c.page_number, c.section,
                       d.title,
                       d.publisher, d.licence, d.source_url, d.tier,
                       1 - (c.embedding <=> CAST(:embedding AS vector)) AS similarity
                FROM agronomy_document_chunk c
                JOIN agronomy_document d ON d.id = c.document_id
                WHERE d.tier <= :maximum_tier
                  AND (
                    d.applicable_regions ? 'national'
                    OR d.applicable_regions ? :agro_climatic_zone
                  )
                ORDER BY c.embedding <=> CAST(:embedding AS vector)
                LIMIT :candidate_limit
                """
            ),
            {
                "embedding": _vector_literal(query_embedding),
                "maximum_tier": maximum_tier,
                "agro_climatic_zone": agro_climatic_zone,
                "candidate_limit": limit * 10,
            },
        )
    ).mappings()
    candidates = [dict(row) for row in rows]
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
