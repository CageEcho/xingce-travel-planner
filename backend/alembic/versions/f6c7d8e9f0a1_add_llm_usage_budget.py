"""persist model usage reservations and rate limits

Revision ID: f6c7d8e9f0a1
Revises: e5b6c7d8e9f0
"""
from alembic import op
import sqlalchemy as sa

revision = "f6c7d8e9f0a1"
down_revision = "e5b6c7d8e9f0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("llm_usage_budget",
                    sa.Column("bucket", sa.Text(), primary_key=True),
                    sa.Column("tokens", sa.BigInteger(), nullable=False, server_default="0"),
                    sa.Column("calls", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_table("llm_usage_budget")
