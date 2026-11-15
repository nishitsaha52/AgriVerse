from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from agriverse.config import Settings
from agriverse.services import reindex
from agriverse.services.retrieval import EmbeddedText, StoredEmbeddings
from tests.fakes import FakeSession


def settings():
    return Settings(_env_file=None, openai_api_key="test-openai", gemini_api_key="test-gemini")


def record(current=False):
    config = settings()
    return SimpleNamespace(
        id=uuid4(),
        content="clean seed",
        embedding_text="leaf lesions",
        embedding=[0.6, 0.8],
        embedding_model=config.openai_embedding_model if current else None,
        gemini_embedding=[0.8, 0.6] if current else None,
        gemini_embedding_model=config.gemini_embedding_model if current else None,
        confirmed_dx="rust",
        confirmed_by=uuid4(),
    )


def vectors(both=True):
    config = settings()
    return StoredEmbeddings(
        "leaf lesions",
        EmbeddedText([0.6, 0.8], "openai", config.openai_embedding_model),
        EmbeddedText([0.8, 0.6], "gemini", config.gemini_embedding_model) if both else None,
    )


def install_session(monkeypatch, db):
    @asynccontextmanager
    async def session():
        yield db

    monkeypatch.setattr(reindex, "SessionFactory", session)
    monkeypatch.setattr(reindex, "get_settings", settings)


async def test_reindex_preserves_confirmations_and_reuses_existing_description(monkeypatch):
    existing = record()
    confirmed_by = existing.confirmed_by
    scan = SimpleNamespace(id=uuid4(), object_key="image.jpg")
    db = FakeSession(scalar_result_values=[[], [scan], []], scalar_values=[existing])
    install_session(monkeypatch, db)
    embed = AsyncMock(return_value=[vectors()])
    read = AsyncMock()
    monkeypatch.setattr(reindex.embedding_service, "embed_documents", embed)
    monkeypatch.setattr(reindex.storage, "read", read)
    await reindex.reindex_embeddings(organization_id=uuid4())
    assert existing.confirmed_dx == "rust" and existing.confirmed_by == confirmed_by
    assert existing.embedding_model == settings().openai_embedding_model
    assert existing.gemini_embedding_model == settings().gemini_embedding_model
    assert db.commits == 1
    read.assert_not_called()
    embed.assert_awaited_once_with(["leaf lesions"])


async def test_reindex_skips_current_document_vectors_without_provider_calls(monkeypatch):
    db = FakeSession(scalar_result_values=[[record(current=True)], [], []])
    install_session(monkeypatch, db)
    embed = AsyncMock()
    monkeypatch.setattr(reindex.embedding_service, "embed_documents", embed)
    await reindex.reindex_embeddings()
    embed.assert_not_called()
    assert db.commits == 0


async def test_partial_reindex_is_committed_but_remains_retryable(monkeypatch):
    existing = record()
    db = FakeSession(scalar_result_values=[[existing], [], []])
    install_session(monkeypatch, db)
    monkeypatch.setattr(
        reindex.embedding_service, "embed_documents", AsyncMock(return_value=[vectors(both=False)])
    )
    with pytest.raises(RuntimeError, match="incomplete"):
        await reindex.reindex_embeddings()
    assert db.commits == 1
    assert existing.embedding_model == settings().openai_embedding_model
    assert reindex.needs_reindex(existing)
