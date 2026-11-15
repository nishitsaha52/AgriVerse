"""Explicit, resumable reindexing; never run paid provider calls during migration."""

import uuid
from typing import Any

import structlog
from sqlalchemy import select

from agriverse.config import get_settings
from agriverse.db import SessionFactory
from agriverse.dependencies import set_tenant_context
from agriverse.models import AgronomyDocumentChunk, Organization, Scan, ScanEmbedding
from agriverse.services.retrieval import embedding_service
from agriverse.services.storage import storage

logger = structlog.get_logger()


def needs_reindex(record: Any) -> bool:
    settings = get_settings()
    return bool(
        record is None
        or (
            settings.openai_api_key.get_secret_value()
            and (
                record.embedding is None
                or record.embedding_model != settings.openai_embedding_model
            )
        )
        or (
            settings.gemini_api_key.get_secret_value()
            and (
                record.gemini_embedding is None
                or record.gemini_embedding_model != settings.gemini_embedding_model
            )
        )
    )


async def reindex_embeddings(
    batch_size: int = 32, organization_id: uuid.UUID | None = None
) -> None:
    settings = get_settings()
    if not (
        settings.openai_api_key.get_secret_value() or settings.gemini_api_key.get_secret_value()
    ):
        raise ValueError("Configure OPENAI_API_KEY or GEMINI_API_KEY before reindexing")
    if batch_size < 1 or batch_size > 64:
        raise ValueError("Batch size must be between 1 and 64")
    updated = failures = 0
    async with SessionFactory() as db:
        cursor: uuid.UUID | None = None
        while True:
            statement = (
                select(AgronomyDocumentChunk).order_by(AgronomyDocumentChunk.id).limit(batch_size)
            )
            if cursor is not None:
                statement = statement.where(AgronomyDocumentChunk.id > cursor)
            rows = list((await db.scalars(statement)).all())
            if not rows:
                break
            cursor = rows[-1].id
            pending = [row for row in rows if needs_reindex(row)]
            if not pending:
                continue
            try:
                vectors = await embedding_service.embed_documents([row.content for row in pending])
                for row, vector in zip(pending, vectors, strict=True):
                    for key, value in vector.columns().items():
                        setattr(row, key, value)
                incomplete = sum(needs_reindex(row) for row in pending)
                await db.commit()
                failures += incomplete
                updated += len(pending)
            except Exception as exc:
                await db.rollback()
                failures += len(pending)
                logger.error("document_reindex_failed", error=type(exc).__name__)

        organizations = (
            [organization_id]
            if organization_id is not None
            else list((await db.scalars(select(Organization.id))).all())
        )
        for org_id in organizations:
            cursor = None
            while True:
                await set_tenant_context(db, org_id)
                scan_statement = (
                    select(Scan)
                    .where(
                        Scan.organization_id == org_id,
                        Scan.status == "completed",
                        Scan.original_filename != "erased",
                    )
                    .order_by(Scan.id)
                    .limit(batch_size)
                )
                if cursor is not None:
                    scan_statement = scan_statement.where(Scan.id > cursor)
                scans = list((await db.scalars(scan_statement)).all())
                if not scans:
                    break
                cursor = scans[-1].id
                scan_sources = [(scan.id, scan.object_key) for scan in scans]
                for scan_id, object_key in scan_sources:
                    try:
                        await set_tenant_context(db, org_id)
                        record = await db.scalar(
                            select(ScanEmbedding).where(
                                ScanEmbedding.scan_id == scan_id,
                                ScanEmbedding.organization_id == org_id,
                            )
                        )
                        if not needs_reindex(record):
                            continue
                        if record is not None and record.embedding_text:
                            vector = (
                                await embedding_service.embed_documents([record.embedding_text])
                            )[0]
                        else:
                            vector = await embedding_service.embed_image(
                                await storage.read(object_key)
                            )
                        if record is None:
                            record = ScanEmbedding(scan_id=scan_id, organization_id=org_id)
                            db.add(record)
                        record.embedding_text = vector.text
                        for key, value in vector.columns().items():
                            setattr(record, key, value)
                        incomplete_record = needs_reindex(record)
                        await db.commit()
                        failures += int(incomplete_record)
                        updated += 1
                    except Exception as exc:
                        await db.rollback()
                        failures += 1
                        logger.error("scan_reindex_failed", error=type(exc).__name__)
    print(f"Reindexed {updated} records; {failures} failed. Existing confirmations were preserved.")
    if failures:
        raise RuntimeError("Reindex incomplete; fix provider/storage configuration and rerun")
