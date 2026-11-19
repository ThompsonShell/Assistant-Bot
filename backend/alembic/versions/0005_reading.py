"""article reading log and study key/value settings

Revision ID: 0005_reading
Revises: 0004_study
Create Date: 2026-11-19
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_reading"
down_revision = "0004_study"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reading_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("url", sa.String(length=1000), nullable=True),
        sa.Column("blurb", sa.String(length=400), nullable=True),
        sa.Column("words_sent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("example_done", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_reading_logs_day", "reading_logs", ["day"])
    op.create_index("ix_reading_logs_status", "reading_logs", ["status"])

    op.create_table(
        "study_kv",
        sa.Column("key", sa.String(length=64), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_table("study_kv")
    op.drop_table("reading_logs")
