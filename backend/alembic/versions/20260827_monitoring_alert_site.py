"""Add explicit site scope for site-wide monitoring alerts.

Revision ID: 20260827_monitoring_alert_site
Revises: 20260825_trigger_semantics
Create Date: 2026-08-27
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260827_monitoring_alert_site"
down_revision: Union[str, None] = "20260825_trigger_semantics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("alerts"):
        return
    columns = {column["name"] for column in inspector.get_columns("alerts")}
    if "site_id" not in columns:
        op.add_column("alerts", sa.Column("site_id", sa.BigInteger(), nullable=True))
        op.create_foreign_key(
            "fk_alerts_site_id_sites", "alerts", "sites", ["site_id"], ["site_id"], ondelete="CASCADE"
        )
        op.create_index("ix_alerts_site_id", "alerts", ["site_id"])
    # Existing equipment/zone alerts keep their normal identity while gaining
    # an explicit site scope for consistent lookup and future data sources.
    op.execute(sa.text("""
        UPDATE alerts AS a
        SET site_id = e.site_id
        FROM equipment AS e
        WHERE a.site_id IS NULL AND a.equipment_id = e.equipment_id
    """))
    op.execute(sa.text("""
        UPDATE alerts AS a
        SET site_id = z.site_id
        FROM zones AS z
        WHERE a.site_id IS NULL AND a.zone_id = z.zone_id
    """))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("alerts"):
        return
    columns = {column["name"] for column in inspector.get_columns("alerts")}
    if "site_id" in columns:
        op.drop_index("ix_alerts_site_id", table_name="alerts")
        op.drop_constraint("fk_alerts_site_id_sites", "alerts", type_="foreignkey")
        op.drop_column("alerts", "site_id")
