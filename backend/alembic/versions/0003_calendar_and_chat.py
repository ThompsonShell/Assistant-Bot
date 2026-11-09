"""calendar tasks and chat messages

Revision ID: 0003_calendar_and_chat
Revises: 0002_github_monitoring
Create Date: 2026-11-09
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_calendar_and_chat"
down_revision = "0002_github_monitoring"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("scheduled_date", sa.Date(), nullable=True),
        sa.Column("duration_minutes", sa.Integer(), nullable=True),
        sa.Column("priority", sa.String(length=16), nullable=False, server_default="medium"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="planned"),
        sa.Column("category", sa.String(length=80), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False, server_default="manual"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_tasks_scheduled_date", "tasks", ["scheduled_date"])
    op.create_index("ix_tasks_status", "tasks", ["status"])

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("ai_generated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_chat_messages_role", "chat_messages", ["role"])
    op.create_index("ix_chat_messages_ts", "chat_messages", ["ts"])


def downgrade() -> None:
    op.drop_table("chat_messages")
    op.drop_table("tasks")
