"""paper diary entries (handwritten page photos)

Revision ID: 0007_paper_entries
Revises: 0006_conversation_state
Create Date: 2026-11-19
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_paper_entries"
down_revision = "0006_conversation_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "paper_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("photo_paths", sa.JSON(), nullable=False),
        sa.Column("transcription", sa.Text(), nullable=False, server_default=""),
        sa.Column("parsed", sa.JSON(), nullable=False),
        sa.Column("minutes", sa.JSON(), nullable=False),
        sa.Column("ai_off_minutes", sa.Integer(), nullable=True),
        sa.Column("confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reminded", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_paper_entries_day", "paper_entries", ["day"], unique=True)
    op.create_index("ix_paper_entries_confirmed", "paper_entries", ["confirmed"])


def downgrade() -> None:
    op.drop_table("paper_entries")
