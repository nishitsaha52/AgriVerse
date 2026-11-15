"""Isolate direct provider embeddings and leave legacy vectors unclassified."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "20261115_0002"
down_revision: str | None = "20260731_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    for table in ("scan_embedding", "agronomy_document_chunk"):
        columns = {column["name"]: column for column in sa.inspect(bind).get_columns(table)}
        dimension = columns["embedding"]["type"].dim
        additions = [
            sa.Column("embedding_model", sa.String(160), nullable=True),
            sa.Column("gemini_embedding", Vector(dimension), nullable=True),
            sa.Column("gemini_embedding_model", sa.String(160), nullable=True),
        ]
        if table == "scan_embedding":
            additions.append(sa.Column("embedding_text", sa.Text(), nullable=True))
        # The initial migration creates live model metadata on fresh installs.
        # Accommodate those columns as well as existing deployed databases.
        for column in additions:
            if column.name not in columns:
                op.add_column(table, column)
        op.alter_column(table, "embedding", nullable=True)
        op.execute(
            f"CREATE INDEX IF NOT EXISTS ix_{table}_gemini_hnsw ON {table} "
            "USING hnsw (gemini_embedding vector_cosine_ops) "
            "WHERE gemini_embedding IS NOT NULL"
        )


def downgrade() -> None:
    # Fail rather than silently hiding tenant rows while checking rollback safety.
    op.execute("SET LOCAL row_security = off")
    for table in ("scan_embedding", "agronomy_document_chunk"):
        relation = sa.table(
            table,
            sa.column("embedding"),
            sa.column("embedding_model"),
            sa.column("gemini_embedding"),
        )
        if op.get_bind().scalar(
            sa.select(sa.func.count())
            .select_from(relation)
            .where(
                sa.or_(
                    relation.c.embedding.is_(None),
                    relation.c.embedding_model.is_not(None),
                    relation.c.gemini_embedding.is_not(None),
                )
            )
        ):
            raise RuntimeError(
                "Cannot restore the legacy vector space after reindexing; "
                "restore a pre-migration backup to roll back indexed data"
            )
    for table in ("scan_embedding", "agronomy_document_chunk"):
        op.execute(f"DROP INDEX IF EXISTS ix_{table}_gemini_hnsw")
        if table == "scan_embedding":
            op.drop_column(table, "embedding_text")
        for column in ("gemini_embedding_model", "gemini_embedding", "embedding_model"):
            op.drop_column(table, column)
        op.alter_column(table, "embedding", nullable=False)
