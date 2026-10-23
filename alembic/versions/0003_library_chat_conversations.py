"""library chat: several discussions instead of a single thread

Revision ID: 0003_library_chat_conversations
Revises: 0002_drop_ai_analysis
Create Date: 2026-10-23 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_library_chat_conversations"
down_revision: str | None = "0002_drop_ai_analysis"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Same rule as back/services/library_chat/history.py:conversation_title, frozen here.
TITLE_LENGTH = 80


def upgrade() -> None:
    op.create_table(
        "library_chat_conversations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
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
        op.f("ix_library_chat_conversations_updated_at"),
        "library_chat_conversations",
        ["updated_at"],
    )
    op.add_column(
        "library_chat_messages", sa.Column("conversation_id", sa.Integer(), nullable=True)
    )

    # The former single thread becomes the first discussion.
    bind = op.get_bind()
    first_question = bind.execute(
        sa.text("SELECT content FROM library_chat_messages WHERE role = 'user' ORDER BY id LIMIT 1")
    ).scalar()
    span = bind.execute(
        sa.text("SELECT MIN(created_at), MAX(created_at) FROM library_chat_messages")
    ).one()
    if span[0] is not None:
        title = " ".join((first_question or "").split()) or "Discussion"
        if len(title) > TITLE_LENGTH:
            title = title[: TITLE_LENGTH - 1].rstrip() + "…"
        conversation_id = bind.execute(
            sa.text(
                "INSERT INTO library_chat_conversations (title, created_at, updated_at) "
                "VALUES (:title, :created_at, :updated_at) RETURNING id"
            ),
            {"title": title, "created_at": span[0], "updated_at": span[1]},
        ).scalar()
        bind.execute(
            sa.text("UPDATE library_chat_messages SET conversation_id = :id"),
            {"id": conversation_id},
        )

    op.alter_column("library_chat_messages", "conversation_id", nullable=False)
    op.create_index(
        op.f("ix_library_chat_messages_conversation_id"),
        "library_chat_messages",
        ["conversation_id"],
    )
    op.create_foreign_key(
        "library_chat_messages_conversation_id_fkey",
        "library_chat_messages",
        "library_chat_conversations",
        ["conversation_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.add_column("llm_jobs", sa.Column("conversation_id", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_llm_jobs_conversation_id"), "llm_jobs", ["conversation_id"])
    op.create_foreign_key(
        "llm_jobs_conversation_id_fkey",
        "llm_jobs",
        "library_chat_conversations",
        ["conversation_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    # Every discussion's messages fall back into the single thread, in id order.
    op.drop_constraint("llm_jobs_conversation_id_fkey", "llm_jobs", type_="foreignkey")
    op.drop_index(op.f("ix_llm_jobs_conversation_id"), table_name="llm_jobs")
    op.drop_column("llm_jobs", "conversation_id")
    op.drop_constraint(
        "library_chat_messages_conversation_id_fkey", "library_chat_messages", type_="foreignkey"
    )
    op.drop_index(
        op.f("ix_library_chat_messages_conversation_id"), table_name="library_chat_messages"
    )
    op.drop_column("library_chat_messages", "conversation_id")
    op.drop_index(
        op.f("ix_library_chat_conversations_updated_at"), table_name="library_chat_conversations"
    )
    op.drop_table("library_chat_conversations")
