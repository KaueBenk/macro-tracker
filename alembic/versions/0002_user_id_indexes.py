"""add user id indexes

Revision ID: 0002_user_id_indexes
Revises: 0001_initial
Create Date: 2025-01-02
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0002_user_id_indexes"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_api_tokens_user_id", "api_tokens", ["user_id"], unique=False)
    op.create_index("ix_foods_user_id", "foods", ["user_id"], unique=False)
    op.create_index("ix_goals_user_id", "goals", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_goals_user_id", table_name="goals")
    op.drop_index("ix_foods_user_id", table_name="foods")
    op.drop_index("ix_api_tokens_user_id", table_name="api_tokens")
