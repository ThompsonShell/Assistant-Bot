"""github monitoring: repos, events, notifications

Revision ID: 0002_github_monitoring
Revises: 0001_initial
Create Date: 2026-11-04
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_github_monitoring"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "github_repos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("full_name", sa.String(length=320), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("etag", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("full_name", name="uq_github_repos_full_name"),
    )
    op.create_index("ix_github_repos_owner", "github_repos", ["owner"])
    op.create_index("ix_github_repos_full_name", "github_repos", ["full_name"])

    op.create_table(
        "github_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("gh_id", sa.String(length=64), nullable=False),
        sa.Column("repo_full_name", sa.String(length=320), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=True),
        sa.Column("actor_login", sa.String(length=120), nullable=False),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("branch", sa.String(length=255), nullable=True),
        sa.Column("number", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=400), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("url", sa.String(length=600), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw", sa.JSON(), nullable=True),
        sa.UniqueConstraint("gh_id", name="uq_github_events_gh_id"),
    )
    op.create_index("ix_github_events_gh_id", "github_events", ["gh_id"])
    op.create_index("ix_github_events_repo_full_name", "github_events", ["repo_full_name"])
    op.create_index("ix_github_events_type", "github_events", ["type"])
    op.create_index("ix_github_events_actor_login", "github_events", ["actor_login"])
    op.create_index("ix_github_events_actor_type", "github_events", ["actor_type"])
    op.create_index("ix_github_events_created_at", "github_events", ["created_at"])

    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=400), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("delivered", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("error", sa.String(length=300), nullable=True),
    )
    op.create_index("ix_notifications_ts", "notifications", ["ts"])
    op.create_index("ix_notifications_category", "notifications", ["category"])
    op.create_index("ix_notifications_channel", "notifications", ["channel"])


def downgrade() -> None:
    op.drop_table("notifications")
    op.drop_table("github_events")
    op.drop_table("github_repos")
