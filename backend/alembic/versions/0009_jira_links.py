"""which bot tasks were already sent to Jira

Revision ID: 0009_jira_links
Revises: 0008_memory
Create Date: 2026-11-20
"""
from alembic import op
import sqlalchemy as sa

revision = "0009_jira_links"
down_revision = "0008_memory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "jira_links",
        sa.Column("task_id", sa.Integer(), primary_key=True),
        sa.Column("jira_key", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("jira_links")
