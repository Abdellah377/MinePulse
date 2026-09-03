"""Add equipment.home_zone_id and backfill excavator homes.

Revision ID: 20260903_home_zone
Revises: 20260831_actions_opt
Create Date: 2026-09-03
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260903_home_zone"
down_revision: Union[str, None] = "20260831_actions_opt"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("equipment"):
        return
    columns = {column["name"] for column in inspector.get_columns("equipment")}
    if "home_zone_id" not in columns:
        op.add_column(
            "equipment",
            sa.Column("home_zone_id", sa.BigInteger(), nullable=True),
        )
        op.create_foreign_key(
            "fk_equipment_home_zone_id",
            "equipment",
            "zones",
            ["home_zone_id"],
            ["zone_id"],
            ondelete="SET NULL",
        )
    op.execute(
        sa.text(
            """
            UPDATE equipment AS e
            SET home_zone_id = z.zone_id
            FROM zones AS z
            WHERE e.home_zone_id IS NULL
              AND e.site_id = z.site_id
              AND (
                (e.code IN ('EXC-001', 'EXC-003') AND z.code = 'BANC_A')
                OR (e.code = 'EXC-002' AND z.code = 'BANC_B')
              )
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("equipment"):
        return
    columns = {column["name"] for column in inspector.get_columns("equipment")}
    if "home_zone_id" not in columns:
        return
    op.drop_constraint("fk_equipment_home_zone_id", "equipment", type_="foreignkey")
    op.drop_column("equipment", "home_zone_id")
