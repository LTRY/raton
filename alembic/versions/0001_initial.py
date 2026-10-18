"""initial schema (squash of the former migrations 0001-0047)

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-18 07:55:24.128521
"""

from collections.abc import Sequence

import pgvector.sqlalchemy.vector
import sqlalchemy as sa

from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # pgvector backs video_note_chunks.embedding.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_table(
        "channels",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("yt_channel_id", sa.String(length=255), nullable=True),
        sa.Column("auto_metadata_enabled", sa.Boolean(), nullable=False),
        sa.Column("auto_shorts_enabled", sa.Boolean(), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("category_labels", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("keywords", sa.Text(), nullable=True),
        sa.Column("avatar_path", sa.String(length=2048), nullable=True),
        sa.Column("banner_path", sa.String(length=2048), nullable=True),
        sa.Column("metadata_fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_scanned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("rating >= 0 AND rating <= 5", name="ck_channels_rating_range"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_channels_auto_metadata_enabled"),
        "channels",
        ["auto_metadata_enabled"],
        unique=False,
    )
    op.create_index(
        op.f("ix_channels_auto_shorts_enabled"), "channels", ["auto_shorts_enabled"], unique=False
    )
    op.create_index(
        op.f("ix_channels_metadata_fetched_at"), "channels", ["metadata_fetched_at"], unique=False
    )
    op.create_index(op.f("ix_channels_rating"), "channels", ["rating"], unique=False)
    op.create_index(op.f("ix_channels_url"), "channels", ["url"], unique=True)
    op.create_index(op.f("ix_channels_yt_channel_id"), "channels", ["yt_channel_id"], unique=False)
    op.create_table(
        "library_chat_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("sources", sa.Text(), nullable=True),
        sa.Column("channel_sources", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "playlists",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("source_url", sa.String(length=2048), nullable=True),
        sa.Column("yt_playlist_id", sa.String(length=255), nullable=True),
        sa.Column("category_labels", sa.Text(), nullable=True),
        sa.Column("free_listening", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_playlists_yt_playlist_id"), "playlists", ["yt_playlist_id"], unique=False
    )
    op.create_table(
        "videos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("channel_id", sa.Integer(), nullable=True),
        sa.Column("yt_video_id", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("media_type", sa.String(length=20), nullable=False),
        sa.Column("download_source", sa.String(length=20), nullable=False),
        sa.Column("imported_via_form", sa.Boolean(), nullable=False),
        sa.Column("is_new", sa.Boolean(), nullable=False),
        sa.Column("list_state", sa.String(length=20), nullable=True),
        sa.Column("category_labels", sa.Text(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("downloaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("watched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("folder_path", sa.Text(), nullable=False),
        sa.Column("video_path", sa.Text(), nullable=True),
        sa.Column("audio_path", sa.Text(), nullable=True),
        sa.Column("thumbnail_path", sa.Text(), nullable=True),
        sa.Column("metadata_path", sa.Text(), nullable=True),
        sa.Column("subtitle_path", sa.Text(), nullable=True),
        sa.Column("transcript_path", sa.Text(), nullable=True),
        sa.Column(
            "transcript_status",
            sa.Enum("missing", "downloaded", "failed", name="transcript_status"),
            nullable=False,
        ),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("view_count", sa.BigInteger(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("ai_analysis_json", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("rating >= 0 AND rating <= 5", name="ck_videos_rating_range"),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("yt_video_id", name="uq_videos_yt_video_id"),
    )
    op.create_check_constraint(
        "ck_videos_download_source", "videos", "download_source IN ('auto', 'manual')"
    )
    op.create_index(op.f("ix_videos_channel_id"), "videos", ["channel_id"], unique=False)
    op.create_index(op.f("ix_videos_downloaded_at"), "videos", ["downloaded_at"], unique=False)
    op.create_index(
        op.f("ix_videos_imported_via_form"), "videos", ["imported_via_form"], unique=False
    )
    op.create_index(op.f("ix_videos_is_new"), "videos", ["is_new"], unique=False)
    op.create_index(op.f("ix_videos_list_state"), "videos", ["list_state"], unique=False)
    op.create_index(op.f("ix_videos_published_at"), "videos", ["published_at"], unique=False)
    op.create_index(op.f("ix_videos_rating"), "videos", ["rating"], unique=False)
    op.create_index(op.f("ix_videos_view_count"), "videos", ["view_count"], unique=False)
    op.create_index(op.f("ix_videos_watched_at"), "videos", ["watched_at"], unique=False)
    op.create_index(op.f("ix_videos_yt_video_id"), "videos", ["yt_video_id"], unique=False)
    op.create_table(
        "download_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("channel_id", sa.Integer(), nullable=True),
        sa.Column("video_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_download_jobs_status"), "download_jobs", ["status"], unique=False)
    op.create_table(
        "llm_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("video_id", sa.Integer(), nullable=True),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("question", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="queued", nullable=False),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("sources", sa.Text(), nullable=True),
        sa.Column("tool_calls", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("model", sa.String(length=50), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_llm_jobs_status"), "llm_jobs", ["status"], unique=False)
    op.create_index(op.f("ix_llm_jobs_video_id"), "llm_jobs", ["video_id"], unique=False)
    op.create_table(
        "playlist_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("playlist_id", sa.Integer(), nullable=False),
        sa.Column("video_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["playlist_id"], ["playlists.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("playlist_id", "video_id", name="uq_playlist_items_playlist_video"),
    )
    op.create_index(
        "ix_playlist_items_playlist_position",
        "playlist_items",
        ["playlist_id", "position"],
        unique=False,
    )
    op.create_index(
        op.f("ix_playlist_items_playlist_id"), "playlist_items", ["playlist_id"], unique=False
    )
    op.create_index(
        op.f("ix_playlist_items_video_id"), "playlist_items", ["video_id"], unique=False
    )
    op.create_table(
        "video_note_chunks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("video_id", sa.Integer(), nullable=False),
        sa.Column("section", sa.String(length=100), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(dim=1024), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_video_note_chunks_video_id"), "video_note_chunks", ["video_id"], unique=False
    )
    op.create_table(
        "video_sponsor_segments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("video_id", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=20), nullable=False),
        sa.Column("start_seconds", sa.Float(), nullable=False),
        sa.Column("end_seconds", sa.Float(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_video_sponsor_segments_video_id"),
        "video_sponsor_segments",
        ["video_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_video_sponsor_segments_video_id"), table_name="video_sponsor_segments")
    op.drop_table("video_sponsor_segments")
    op.drop_index(op.f("ix_video_note_chunks_video_id"), table_name="video_note_chunks")
    op.drop_table("video_note_chunks")
    op.drop_index("ix_playlist_items_playlist_position", table_name="playlist_items")
    op.drop_index(op.f("ix_playlist_items_video_id"), table_name="playlist_items")
    op.drop_index(op.f("ix_playlist_items_playlist_id"), table_name="playlist_items")
    op.drop_table("playlist_items")
    op.drop_index(op.f("ix_llm_jobs_video_id"), table_name="llm_jobs")
    op.drop_index(op.f("ix_llm_jobs_status"), table_name="llm_jobs")
    op.drop_table("llm_jobs")
    op.drop_index(op.f("ix_download_jobs_status"), table_name="download_jobs")
    op.drop_table("download_jobs")
    op.drop_index(op.f("ix_videos_yt_video_id"), table_name="videos")
    op.drop_index(op.f("ix_videos_watched_at"), table_name="videos")
    op.drop_index(op.f("ix_videos_view_count"), table_name="videos")
    op.drop_index(op.f("ix_videos_rating"), table_name="videos")
    op.drop_index(op.f("ix_videos_published_at"), table_name="videos")
    op.drop_index(op.f("ix_videos_list_state"), table_name="videos")
    op.drop_index(op.f("ix_videos_is_new"), table_name="videos")
    op.drop_index(op.f("ix_videos_imported_via_form"), table_name="videos")
    op.drop_index(op.f("ix_videos_downloaded_at"), table_name="videos")
    op.drop_index(op.f("ix_videos_channel_id"), table_name="videos")
    op.drop_table("videos")
    op.drop_index(op.f("ix_playlists_yt_playlist_id"), table_name="playlists")
    op.drop_table("playlists")
    op.drop_table("library_chat_messages")
    op.drop_index(op.f("ix_channels_yt_channel_id"), table_name="channels")
    op.drop_index(op.f("ix_channels_url"), table_name="channels")
    op.drop_index(op.f("ix_channels_rating"), table_name="channels")
    op.drop_index(op.f("ix_channels_metadata_fetched_at"), table_name="channels")
    op.drop_index(op.f("ix_channels_auto_shorts_enabled"), table_name="channels")
    op.drop_index(op.f("ix_channels_auto_metadata_enabled"), table_name="channels")
    op.drop_table("channels")
    op.drop_table("app_settings")
    op.execute("DROP TYPE IF EXISTS transcript_status")
    op.execute("DROP EXTENSION IF EXISTS vector")
