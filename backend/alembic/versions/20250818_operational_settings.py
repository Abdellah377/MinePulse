"""Add operational_settings table.

Revision ID: 20250818_ops_settings
Revises:
Create Date: 2025-08-18

This is NOT a full MinePulse schema. The operational database is created from
shema_postgre/minepulse_schema.sql then `alembic stamp head`. `upgrade head`
only creates operational_settings when that table is missing (no-op otherwise).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20250818_ops_settings"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("operational_settings"):
        return
    op.create_table(
        "operational_settings",
        sa.Column("setting_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("setting_id"),
        sa.UniqueConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("operational_settings")
