"""users: each user keeps their own Vu, stars, cloches, playlists and discussions

The fiches, their files and generated notes stay shared. Everything that was personal moves to a
first user, "Moi", so nothing changes for the person who used Raton alone.

Revision ID: 0004_users
Revises: 0003_library_chat_conversations
Create Date: 2026-10-24 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004_users"
down_revision: str | None = "0003_library_chat_conversations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen copies of back/models/user.py and back/services/common/users.py at this revision.
FIRST_USER_NAME = "Moi"
USER_NAME_LENGTH = 40
# The app_settings keys that become per-user (back/services/common/settings.py).
USER_SETTING_KEYS = (
    "video_library_views",
    "screen_time_video_today_limit_minutes",
    "screen_time_short_today_limit_minutes",
    "screen_time_podcast_today_limit_minutes",
    "screen_time_music_today_limit_minutes",
    "raton_last_seen_at",
    "raton_session_previous_visit_at",
    "raton_visit_shown",
)
# Tables that gain an owner: (table, owner optional, rows given to the first user). An owned
# row goes with its user; an optional owner is only forgotten.
OWNED = (
    ("playlists", False, None),
    ("library_chat_conversations", False, None),
    ("download_jobs", True, "status IN ('played', 'prompt')"),
    ("llm_jobs", True, "kind IN ('chat', 'library_chat')"),
)


def _keys_sql() -> str:
    return ", ".join(f"'{key}'" for key in USER_SETTING_KEYS)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=USER_NAME_LENGTH), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "user_videos",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("video_id", sa.Integer(), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("list_state", sa.String(length=20), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("is_new", sa.Boolean(), nullable=False),
        sa.Column("watched_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("rating >= 0 AND rating <= 5", name="ck_user_videos_rating_range"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "video_id"),
    )
    op.create_index(op.f("ix_user_videos_video_id"), "user_videos", ["video_id"])
    op.create_table(
        "user_channels",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("channel_id", sa.Integer(), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("auto_metadata_enabled", sa.Boolean(), nullable=False),
        sa.Column("auto_shorts_enabled", sa.Boolean(), nullable=False),
        sa.CheckConstraint("rating >= 0 AND rating <= 5", name="ck_user_channels_rating_range"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "channel_id"),
    )
    op.create_index(op.f("ix_user_channels_channel_id"), "user_channels", ["channel_id"])
    op.create_table(
        "user_settings",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "key"),
    )

    bind = op.get_bind()
    user_id = bind.execute(
        sa.text("INSERT INTO users (name) VALUES (:name) RETURNING id"), {"name": FIRST_USER_NAME}
    ).scalar()
    params = {"user_id": user_id}
    bind.execute(
        sa.text(
            "INSERT INTO user_videos (user_id, video_id, rating, list_state, comment, is_new, "
            "watched_at) SELECT :user_id, id, rating, list_state, comment, is_new, watched_at "
            "FROM videos WHERE rating <> 0 OR list_state IS NOT NULL OR comment IS NOT NULL "
            "OR is_new OR watched_at IS NOT NULL"
        ),
        params,
    )
    bind.execute(
        sa.text(
            "INSERT INTO user_channels (user_id, channel_id, rating, auto_metadata_enabled, "
            "auto_shorts_enabled) SELECT :user_id, id, rating, auto_metadata_enabled, "
            "auto_shorts_enabled FROM channels WHERE rating <> 0 "
            "OR auto_metadata_enabled OR auto_shorts_enabled"
        ),
        params,
    )
    bind.execute(
        sa.text(
            "INSERT INTO user_settings (user_id, key, value) SELECT :user_id, key, value "
            f"FROM app_settings WHERE key IN ({_keys_sql()})"
        ),
        params,
    )
    bind.execute(sa.text(f"DELETE FROM app_settings WHERE key IN ({_keys_sql()})"))

    for table, nullable, where in OWNED:
        op.add_column(table, sa.Column("user_id", sa.Integer(), nullable=True))
        bind.execute(
            sa.text(
                f"UPDATE {table} SET user_id = :user_id" + (f" WHERE {where}" if where else "")
            ),
            params,
        )
        if not nullable:
            op.alter_column(table, "user_id", nullable=False)
        op.create_index(op.f(f"ix_{table}_user_id"), table, ["user_id"])
        op.create_foreign_key(
            f"{table}_user_id_fkey",
            table,
            "users",
            ["user_id"],
            ["id"],
            ondelete="SET NULL" if nullable else "CASCADE",
        )

    for index in ("is_new", "list_state", "rating"):
        op.drop_index(op.f(f"ix_videos_{index}"), table_name="videos")
    op.drop_constraint("ck_videos_rating_range", "videos", type_="check")
    for column in ("rating", "list_state", "comment", "is_new"):
        op.drop_column("videos", column)
    for index in ("auto_metadata_enabled", "auto_shorts_enabled", "rating"):
        op.drop_index(op.f(f"ix_channels_{index}"), table_name="channels")
    op.drop_constraint("ck_channels_rating_range", "channels", type_="check")
    for column in ("rating", "auto_metadata_enabled", "auto_shorts_enabled"):
        op.drop_column("channels", column)


def downgrade() -> None:
    # The oldest user's state goes back into the shared columns; the other users' is lost.
    bind = op.get_bind()
    user_id = bind.execute(sa.text("SELECT MIN(id) FROM users")).scalar()
    params = {"user_id": user_id}

    op.add_column(
        "channels",
        sa.Column("auto_metadata_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "channels",
        sa.Column("auto_shorts_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "channels",
        sa.Column(
            "rating",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_channels_rating_range", "channels", "rating >= 0 AND rating <= 5"
    )
    for index in ("auto_metadata_enabled", "auto_shorts_enabled", "rating"):
        op.create_index(op.f(f"ix_channels_{index}"), "channels", [index])
    op.add_column(
        "videos", sa.Column("is_new", sa.Boolean(), server_default=sa.false(), nullable=False)
    )
    op.add_column("videos", sa.Column("list_state", sa.String(length=20), nullable=True))
    op.add_column("videos", sa.Column("comment", sa.Text(), nullable=True))
    op.add_column(
        "videos", sa.Column("rating", sa.Integer(), server_default=sa.text("0"), nullable=False)
    )
    op.create_check_constraint("ck_videos_rating_range", "videos", "rating >= 0 AND rating <= 5")
    for index in ("is_new", "list_state", "rating"):
        op.create_index(op.f(f"ix_videos_{index}"), "videos", [index])

    if user_id is not None:
        bind.execute(
            sa.text(
                "UPDATE videos SET rating = s.rating, list_state = s.list_state, "
                "comment = s.comment, is_new = s.is_new FROM user_videos s "
                "WHERE s.video_id = videos.id AND s.user_id = :user_id"
            ),
            params,
        )
        bind.execute(
            sa.text(
                "UPDATE channels SET rating = s.rating, "
                "auto_metadata_enabled = s.auto_metadata_enabled, "
                "auto_shorts_enabled = s.auto_shorts_enabled FROM user_channels s "
                "WHERE s.channel_id = channels.id AND s.user_id = :user_id"
            ),
            params,
        )
        bind.execute(
            sa.text(
                "INSERT INTO app_settings (key, value) SELECT key, value FROM user_settings "
                f"WHERE user_id = :user_id AND key IN ({_keys_sql()})"
            ),
            params,
        )
        for table, nullable, _where in OWNED:
            if not nullable:
                bind.execute(sa.text(f"DELETE FROM {table} WHERE user_id <> :user_id"), params)

    for table, _nullable, _where in OWNED:
        op.drop_constraint(f"{table}_user_id_fkey", table, type_="foreignkey")
        op.drop_index(op.f(f"ix_{table}_user_id"), table_name=table)
        op.drop_column(table, "user_id")
    op.drop_table("user_settings")
    op.drop_index(op.f("ix_user_channels_channel_id"), table_name="user_channels")
    op.drop_table("user_channels")
    op.drop_index(op.f("ix_user_videos_video_id"), table_name="user_videos")
    op.drop_table("user_videos")
    op.drop_table("users")
