"""knowledge catalog: governance fields, ticket / route / history_plan / tag_dict

Revision ID: a7b8c9d0e1f2
Revises: f6c7d8e9f0a1
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "a7b8c9d0e1f2"
down_revision = "f6c7d8e9f0a1"
branch_labels = None
depends_on = None

GOVERNED = ("hotel", "restaurant", "poi", "vehicle")


def _governance() -> list[sa.Column]:
    return [sa.Column("source_type", sa.Text()), sa.Column("source_ref", sa.Text()),
            sa.Column("verified_status", sa.Text(), nullable=False, server_default="verified"),
            sa.Column("verified_by", sa.Text()), sa.Column("verified_at", sa.Date()), sa.Column("review_due", sa.Date())]


def _audit() -> list[sa.Column]:
    return [sa.Column("status", sa.Text(), nullable=False, server_default="active"),
            sa.Column("is_synthetic", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False)]


def upgrade() -> None:
    op.add_column("supplier", sa.Column("category", sa.Text()))
    for table in GOVERNED:
        for col in _governance():
            op.add_column(table, col)
        op.create_index(f"ix_{table}_verified_status", table, ["verified_status"])
    op.create_table(
        "ticket",
        sa.Column("ticket_id", sa.Text(), primary_key=True),
        sa.Column("poi_id", sa.Text(), sa.ForeignKey("poi.poi_id")),
        sa.Column("city", sa.Text(), nullable=False), sa.Column("name_zh", sa.Text(), nullable=False),
        sa.Column("ticket_type", sa.Text(), nullable=False),
        sa.Column("reservation_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("lead_time_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("child_age_max", sa.Integer()), sa.Column("refundable", sa.Boolean()),
        sa.Column("valid_season", sa.Text()), sa.Column("notes", sa.Text()),
        sa.Column("supplier_id", sa.Text(), sa.ForeignKey("supplier.supplier_id")),
        *_audit(), *_governance())
    op.create_index("ix_ticket_poi", "ticket", ["poi_id"])
    op.create_table(
        "route",
        sa.Column("route_id", sa.Text(), primary_key=True),
        sa.Column("name_zh", sa.Text(), nullable=False), sa.Column("city", sa.Text(), nullable=False),
        sa.Column("theme", sa.Text(), nullable=False), sa.Column("duration_type", sa.Text(), nullable=False),
        sa.Column("poi_ids", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("total_minutes", sa.Integer(), nullable=False), sa.Column("intensity", sa.Text(), nullable=False),
        sa.Column("accessible", sa.Boolean()),
        sa.Column("suitable_for", postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("tags", postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("highlights", sa.Text()), sa.Column("notes", sa.Text()),
        *_audit(), *_governance())
    op.create_index("ix_route_city_theme", "route", ["city", "theme"])
    arr = lambda t: postgresql.ARRAY(t)  # noqa: E731
    op.create_table(
        "history_plan",
        sa.Column("plan_id", sa.Text(), primary_key=True),
        sa.Column("travel_month", sa.Text(), nullable=False), sa.Column("party_type", sa.Text(), nullable=False),
        sa.Column("adults", sa.Integer(), nullable=False), sa.Column("children", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("child_ages", arr(sa.Integer()), nullable=False, server_default="{}"),
        sa.Column("with_elderly", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("cities", arr(sa.Text()), nullable=False), sa.Column("days", sa.Integer(), nullable=False),
        sa.Column("budget_band", sa.Text()),
        sa.Column("hotel_tier", arr(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("interests", arr(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("dietary", arr(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("accessibility", sa.Text()),
        sa.Column("hotel_ids", arr(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("route_ids", arr(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("summary", sa.Text(), nullable=False), sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("rework_rounds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("client_rating", sa.Integer()),
        sa.Column("bad_case_tags", arr(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("lessons", sa.Text()),
        sa.Column("source_type", sa.Text(), nullable=False, server_default="historical_order"),
        sa.Column("verified_status", sa.Text(), nullable=False, server_default="verified"),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("desensitized", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.create_table(
        "tag_dict",
        sa.Column("tag", sa.Text(), primary_key=True), sa.Column("label_zh", sa.Text(), nullable=False),
        sa.Column("tag_group", sa.Text(), nullable=False),
        sa.Column("applies_to", arr(sa.Text()), nullable=False, server_default="{}"))


def downgrade() -> None:
    op.drop_table("tag_dict")
    op.drop_table("history_plan")
    op.drop_index("ix_route_city_theme", table_name="route")
    op.drop_table("route")
    op.drop_index("ix_ticket_poi", table_name="ticket")
    op.drop_table("ticket")
    for table in GOVERNED:
        op.drop_index(f"ix_{table}_verified_status", table_name=table)
        for col in ("review_due", "verified_at", "verified_by", "verified_status", "source_ref", "source_type"):
            op.drop_column(table, col)
    op.drop_column("supplier", "category")
