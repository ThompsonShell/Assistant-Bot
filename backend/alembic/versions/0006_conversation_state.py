"""conversation state for guided bot flows

Revision ID: 0006_conversation_state
Revises: 0005_reading
Create Date: 2026-11-19
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_conversation_state"
down_revision = "0005_reading"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation_state",
        sa.Column("key", sa.String(length=32), primary_key=True),
        sa.Column("state", sa.String(length=64), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("conversation_state")
