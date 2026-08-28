"""Add optional developer-only investigation debug_trace JSONB.

Revision ID: 20260829_ai_debug_trace
Revises: 20260827_alert_operational_time
Create Date: 2026-08-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "20260829_ai_debug_trace"
down_revision: Union[str, None] = "20260827_alert_operational_time"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("ai_investigations"):
        return
    columns = {column["name"] for column in inspector.get_columns("ai_investigations")}
    if "debug_trace" not in columns:
        op.add_column("ai_investigations", sa.Column("debug_trace", JSONB(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("ai_investigations"):
        return
    columns = {column["name"] for column in inspector.get_columns("ai_investigations")}
    if "debug_trace" in columns:
        op.drop_column("ai_investigations", "debug_trace")
