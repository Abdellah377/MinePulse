"""Add durable AI investigation audit records.

Revision ID: 20260824_ai_investigations
Revises: 20250818_ops_settings
Create Date: 2026-08-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260824_ai_investigations"
down_revision: Union[str, None] = "20250818_ops_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("ai_investigations"):
        return
    op.create_table(
        "ai_investigations",
        sa.Column("investigation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("trigger_type", sa.String(length=50), nullable=False),
        sa.Column("trigger_source", sa.String(length=120), nullable=False),
        sa.Column("site_id", sa.BigInteger(), nullable=False),
        sa.Column("shift_id", sa.BigInteger(), nullable=True),
        sa.Column("equipment_id", sa.BigInteger(), nullable=True),
        sa.Column("zone_id", sa.BigInteger(), nullable=True),
        sa.Column("iteration_count", sa.Integer(), nullable=False),
        sa.Column("max_iterations", sa.Integer(), nullable=False),
        sa.Column("graph_version", sa.String(length=40), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("model", sa.String(length=160), nullable=False),
        sa.Column("trigger", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("operational_context", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("hypotheses", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("requested_information", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("contradictions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("conclusion", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("recommendation", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["site_id"], ["sites.site_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["shift_id"], ["shifts.shift_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["equipment_id"], ["equipment.equipment_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["zone_id"], ["zones.zone_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("investigation_id"),
    )
    op.create_index(
        "idx_ai_investigations_site_created",
        "ai_investigations",
        ["site_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "idx_ai_investigations_status",
        "ai_investigations",
        ["status", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("ai_investigations"):
        op.drop_table("ai_investigations")
