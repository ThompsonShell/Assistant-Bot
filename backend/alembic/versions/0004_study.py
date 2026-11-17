"""self-study: vocabulary cards, diary entries, quiz sessions

Revision ID: 0004_study
Revises: 0003_calendar_and_chat
Create Date: 2026-11-17
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_study"
down_revision = "0003_calendar_and_chat"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vocab_cards",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("word", sa.String(length=200), nullable=False),
        sa.Column("meaning", sa.String(length=500), nullable=False),
        sa.Column("example", sa.String(length=500), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("interval_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ease", sa.Float(), nullable=False, server_default="2.5"),
        sa.Column("reps", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lapses", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_reviewed", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_vocab_cards_word", "vocab_cards", ["word"])
    op.create_index("ix_vocab_cards_due_date", "vocab_cards", ["due_date"])

    op.create_table(
        "diary_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("learned", sa.Text(), nullable=False, server_default=""),
        sa.Column("recalled", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_diary_entries_day", "diary_entries", ["day"], unique=True)

    op.create_table(
        "quiz_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("questions", sa.JSON(), nullable=False),
        sa.Column("index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("correct", sa.Float(), nullable=False, server_default="0"),
        sa.Column("finished", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_quiz_sessions_finished", "quiz_sessions", ["finished"])


def downgrade() -> None:
    op.drop_table("quiz_sessions")
    op.drop_table("diary_entries")
    op.drop_table("vocab_cards")
