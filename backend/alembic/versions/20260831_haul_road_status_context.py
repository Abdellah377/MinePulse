"""Add operator-facing haul-road description and closure reason columns.

Revision ID: 20260831_haul_road_status_context
Revises: 20260829_ai_debug_trace
Create Date: 2026-08-31
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260831_haul_road_status_context"
down_revision: Union[str, None] = "20260829_ai_debug_trace"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = (
    ("description", sa.Text()),
    ("status_reason", sa.String(length=40)),
    ("status_note", sa.Text()),
    ("status_changed_at", sa.DateTime(timezone=True)),
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("haul_roads"):
        return
    existing = {column["name"] for column in inspector.get_columns("haul_roads")}
    for name, column_type in _COLUMNS:
        if name not in existing:
            op.add_column("haul_roads", sa.Column(name, column_type, nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("haul_roads"):
        return
    existing = {column["name"] for column in inspector.get_columns("haul_roads")}
    for name, _column_type in reversed(_COLUMNS):
        if name in existing:
            op.drop_column("haul_roads", name)
