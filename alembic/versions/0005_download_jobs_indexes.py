"""download_jobs: index what the playback readers filter on

The Historique, the resume position and the cards' progress bars read a user's `played` rows
(`user_id`, `status`, newest first) or a fiche's (`video_id`). Without these indexes each read
scans the table, which gets a row per playback report and only grows. `video_id` also serves the
`ON DELETE SET NULL` of the fiches: deleting one scanned the whole table. The composite index
covers `user_id` on its own, so the single-column one goes.

Revision ID: 0005_download_jobs_indexes
Revises: 0004_users
Create Date: 2026-11-10 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005_download_jobs_indexes"
down_revision: str | None = "0004_users"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_download_jobs_user_status_created",
        "download_jobs",
        ["user_id", "status", "created_at"],
    )
    op.create_index(op.f("ix_download_jobs_video_id"), "download_jobs", ["video_id"])
    op.drop_index(op.f("ix_download_jobs_user_id"), table_name="download_jobs")


def downgrade() -> None:
    op.create_index(op.f("ix_download_jobs_user_id"), "download_jobs", ["user_id"])
    op.drop_index(op.f("ix_download_jobs_video_id"), table_name="download_jobs")
    op.drop_index("ix_download_jobs_user_status_created", table_name="download_jobs")
