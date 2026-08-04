"""Initial AgriVerse schema with pgvector and tenant RLS."""

from collections.abc import Sequence

from alembic import op

from agriverse import models  # noqa: F401
from agriverse.db import Base

revision: str = "20260731_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_TABLES = (
    "membership",
    "farm",
    "field",
    "soil_test",
    "crop_recommendation",
    "weather_snapshot",
    "weather_alert",
    "scan",
    "scan_embedding",
    "diagnosis",
    "farmer_outcome_feedback",
    "agronomist_review_queue",
    "usage_record",
    "audit_log",
    "agent_conversation",
    "agent_message",
    "idempotency_record",
    "refresh_session",
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_scan_embedding_hnsw "
        "ON scan_embedding USING hnsw (embedding vector_cosine_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_document_chunk_hnsw "
        "ON agronomy_document_chunk USING hnsw (embedding vector_cosine_ops)"
    )
    for table in TENANT_TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY tenant_isolation ON "{table}" '
            "USING (organization_id = "
            "NULLIF(current_setting('app.org_id', true), '')::uuid) "
            "WITH CHECK (organization_id = "
            "NULLIF(current_setting('app.org_id', true), '')::uuid)"
        )


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
