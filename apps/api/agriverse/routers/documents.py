import re

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from agriverse.audit import record_audit
from agriverse.db import get_db
from agriverse.dependencies import enforce_ai_quota, require_permissions
from agriverse.models import AgronomyDocument, AgronomyDocumentChunk
from agriverse.schemas import DocumentIngest, DocumentRead
from agriverse.security import Principal
from agriverse.services.retrieval import embedding_service
from agriverse.services.safety import contains_prompt_injection

router = APIRouter(prefix="/documents", tags=["agronomy documents"])


def semantically_chunk(text: str, *, target_words: int = 384) -> list[str]:
    """Create bounded paragraph-aware chunks with roughly 15% overlap."""
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    overlap_words = max(1, int(target_words * 0.15))
    chunks: list[str] = []
    current: list[str] = []
    for paragraph in paragraphs:
        words = paragraph.split()
        if current and len(current) + len(words) > target_words:
            chunks.append(" ".join(current))
            current = current[-overlap_words:]
        while len(words) > target_words:
            available = max(1, target_words - len(current))
            current.extend(words[:available])
            words = words[available:]
            chunks.append(" ".join(current))
            current = current[-overlap_words:]
        current.extend(words)
    if current:
        chunks.append(" ".join(current))
    return chunks


def validate_licence(licence: str) -> None:
    normalized = licence.upper().replace("_", "-").replace(" ", "-")
    if "BY-NC" in normalized or "NONCOMMERCIAL" in normalized:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Non-commercial material cannot be added to the production corpus",
        )


@router.post("", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def ingest_document(
    payload: DocumentIngest,
    principal: Principal = Depends(require_permissions("document:write")),
    quota_principal: Principal = Depends(enforce_ai_quota),
    db: AsyncSession = Depends(get_db),
) -> DocumentRead:
    del quota_principal
    if principal.role != "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only a super administrator can publish global retrieval documents",
        )
    validate_licence(payload.licence)
    regions = sorted(
        {region.strip().lower() for region in payload.applicable_regions if region.strip()}
    )
    if not regions:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="At least one applicable region is required",
        )
    pending_chunks: list[tuple[int | None, str, str]] = []
    for source_section in payload.sections:
        if contains_prompt_injection(source_section.content):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Document content contains instruction-like prompt injection text",
            )
        pending_chunks.extend(
            (source_section.page_number, source_section.section, content)
            for content in semantically_chunk(source_section.content)
        )
    texts = [content for _, _, content in pending_chunks]
    embeddings = await embedding_service.embed_texts(texts)
    if len(embeddings) != len(pending_chunks):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Embedding provider returned an incomplete result",
        )

    document = AgronomyDocument(
        title=payload.title,
        publisher=payload.publisher,
        licence=payload.licence,
        source_url=str(payload.source_url),
        tier=payload.tier,
        applicable_regions=regions,
        retrieved_at=payload.retrieved_at,
    )
    db.add(document)
    await db.flush()
    for (page_number, section, content), embedding in zip(
        pending_chunks,
        embeddings,
        strict=True,
    ):
        db.add(
            AgronomyDocumentChunk(
                document_id=document.id,
                page_number=page_number,
                section=section,
                content=content,
                embedding=embedding,
            )
        )
    record_audit(
        db,
        principal,
        action="document.ingested",
        resource_type="agronomy_document",
        resource_id=document.id,
        after={
            "title": document.title,
            "publisher": document.publisher,
            "licence": document.licence,
            "tier": document.tier,
            "regions": regions,
            "chunk_count": len(pending_chunks),
        },
    )
    await db.commit()
    return DocumentRead(
        id=document.id,
        title=document.title,
        publisher=document.publisher,
        licence=document.licence,
        source_url=document.source_url,
        retrieved_at=document.retrieved_at,
        tier=document.tier,
        applicable_regions=document.applicable_regions,
        chunk_count=len(pending_chunks),
    )
