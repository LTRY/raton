"""drop videos.ai_analysis_json (the Analyse IA tab is gone)

Revision ID: 0002_drop_ai_analysis
Revises: 0001_initial
Create Date: 2026-10-18 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_drop_ai_analysis"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("videos", "ai_analysis_json")


def downgrade() -> None:
    op.add_column("videos", sa.Column("ai_analysis_json", sa.Text(), nullable=True))
