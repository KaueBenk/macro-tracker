"""add food source metadata and dataset versions

Revision ID: 0006_food_source_metadata
Revises: 0005_food_taco_source
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006_food_source_metadata"
down_revision: str | None = "0005_food_taco_source"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.add_column("foods", sa.Column("source_version", sa.Text(), nullable=True))
    op.add_column("foods", sa.Column("attribution", sa.Text(), nullable=True))
    op.add_column("foods", sa.Column("barcode", sa.Text(), nullable=True))
    op.add_column("foods", sa.Column("locale", sa.Text(), nullable=True))
    op.add_column("foods", sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("foods", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("foods", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("foods", sa.Column("nutrients", postgresql.JSONB(), nullable=True))
    op.create_index("ix_food_barcode", "foods", ["source", "barcode"])
    op.create_index(
        "ix_food_expires_at",
        "foods",
        ["expires_at"],
        postgresql_where=sa.text("expires_at is not null"),
    )
    op.create_index(
        "ix_food_search_text_trgm",
        "foods",
        ["search_text"],
        postgresql_using="gin",
        postgresql_ops={"search_text": "gin_trgm_ops"},
    )
    op.create_table(
        "dataset_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column(
            "imported_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("record_count", sa.Integer(), nullable=False),
        sa.Column("checksum", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source",
            "version",
            "imported_at",
            name="uq_dataset_version_source_version_imported_at",
        ),
    )


def downgrade() -> None:
    op.drop_table("dataset_versions")
    op.drop_index("ix_food_search_text_trgm", table_name="foods")
    op.drop_index("ix_food_expires_at", table_name="foods")
    op.drop_index("ix_food_barcode", table_name="foods")
    op.drop_column("foods", "nutrients")
    op.drop_column("foods", "archived_at")
    op.drop_column("foods", "expires_at")
    op.drop_column("foods", "fetched_at")
    op.drop_column("foods", "locale")
    op.drop_column("foods", "barcode")
    op.drop_column("foods", "attribution")
    op.drop_column("foods", "source_version")
