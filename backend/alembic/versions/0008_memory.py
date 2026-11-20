"""owner memory facts for the assistant

Revision ID: 0008_memory
Revises: 0007_paper_entries
Create Date: 2026-11-20
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_memory"
down_revision = "0007_paper_entries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "memory_facts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("text", sa.String(length=400), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("memory_facts")
