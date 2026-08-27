"""Separate alert operational occurrence time from persistence time.

Revision ID: 20260827_alert_operational_time
Revises: 20260827_monitoring_alert_site
Create Date: 2026-08-27
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260827_alert_operational_time"
down_revision: Union[str, None] = "20260827_monitoring_alert_site"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("alerts"):
        return
    columns = {column["name"] for column in inspector.get_columns("alerts")}
    if "occurred_at" not in columns:
        op.add_column(
            "alerts",
            sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        )
        # Until this revision, created_at was populated with event time by the
        # simulator and monitor. Preserve that history as the occurrence time.
        op.execute(sa.text("UPDATE alerts SET occurred_at = created_at WHERE occurred_at IS NULL"))
        op.create_index("ix_alerts_occurred_at", "alerts", ["occurred_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("alerts"):
        return
    columns = {column["name"] for column in inspector.get_columns("alerts")}
    if "occurred_at" in columns:
        op.drop_index("ix_alerts_occurred_at", table_name="alerts")
        op.drop_column("alerts", "occurred_at")
