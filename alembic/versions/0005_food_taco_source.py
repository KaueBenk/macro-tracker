"""add TACO metadata and searchable food text

Revision ID: 0005_food_taco_source
Revises: 0004_pending_browser_binding
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.text import normalize_search_text

revision: str = "0005_food_taco_source"
down_revision: str | None = "0004_pending_browser_binding"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("foods", sa.Column("source", sa.String(20), nullable=True))
    op.add_column("foods", sa.Column("source_ref", sa.String(50), nullable=True))
    op.add_column("foods", sa.Column("category", sa.String(100), nullable=True))
    op.add_column("foods", sa.Column("search_text", sa.Text(), nullable=True))
    op.create_index(
        "uq_food_source_ref",
        "foods",
        ["source", "source_ref"],
        unique=True,
        postgresql_where=sa.text("source is not null"),
    )

    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, name, brand, category FROM foods")).mappings()
    for row in rows:
        bind.execute(
            sa.text("UPDATE foods SET search_text = :search_text WHERE id = :id"),
            {
                "id": row["id"],
                "search_text": normalize_search_text(row["name"], row["brand"], row["category"]),
            },
        )


def downgrade() -> None:
    op.drop_index("uq_food_source_ref", table_name="foods")
    op.drop_column("foods", "search_text")
    op.drop_column("foods", "category")
    op.drop_column("foods", "source_ref")
    op.drop_column("foods", "source")
