"""deleted fiches: the scan skips their YouTube id

Revision ID: 0004_deleted_videos
Revises: 0003_library_chat_conversations
Create Date: 2026-10-24 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004_deleted_videos"
down_revision: str | None = "0003_library_chat_conversations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "deleted_videos",
        sa.Column("yt_video_id", sa.String(length=255), nullable=False),
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("yt_video_id"),
    )


def downgrade() -> None:
    op.drop_table("deleted_videos")
