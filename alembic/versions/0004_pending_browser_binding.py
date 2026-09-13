"""bind pending OAuth authorizations to a browser

Revision ID: 0004_pending_browser_binding
Revises: 0003_oauth
Create Date: 2025-01-04
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004_pending_browser_binding"
down_revision: str | None = "0003_oauth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "oauth_pending_auth",
        sa.Column("browser_hash", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("oauth_pending_auth", "browser_hash")
