"""channels.rag_indexed: whether the channel's fiches are indexed by the RAG

Revision ID: 0005_channel_rag_indexed
Revises: 0004_users
Create Date: 2026-10-27 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005_channel_rag_indexed"
down_revision: str | None = "0004_users"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "channels",
        sa.Column("rag_indexed", sa.Boolean(), server_default=sa.true(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("channels", "rag_indexed")
