"""Separate operational trigger type from investigation trigger source.

Revision ID: 20260825_trigger_semantics
Revises: 20260824_ai_investigations
Create Date: 2026-08-25
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260825_trigger_semantics"
down_revision: Union[str, None] = "20260824_ai_investigations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OPERATIONAL_TYPE_SQL = """
CASE COALESCE("trigger"->>'subject', 'OTHER')
    WHEN 'PRODUCTION' THEN 'PRODUCTION_DEVIATION'
    WHEN 'EQUIPMENT' THEN 'EQUIPMENT_ANOMALY'
    WHEN 'CONNECTIVITY' THEN 'CONNECTIVITY_ISSUE'
    WHEN 'MAINTENANCE' THEN 'MAINTENANCE_RISK'
    ELSE 'OPERATIONAL_EVENT'
END
"""


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("ai_investigations"):
        return
    op.execute(
        sa.text(
            f"""
            UPDATE ai_investigations
            SET metadata = COALESCE(metadata, '{{}}'::jsonb) || jsonb_build_object(
                    'legacyTriggerType', trigger_type,
                    'legacyTriggerSource', trigger_source
                ),
                trigger_source = trigger_type,
                trigger_type = {_OPERATIONAL_TYPE_SQL},
                "trigger" = COALESCE("trigger", '{{}}'::jsonb) || jsonb_build_object(
                    'trigger_source', trigger_type,
                    'trigger_type', {_OPERATIONAL_TYPE_SQL}
                )
            WHERE trigger_type IN (
                'AUTOMATIC_MONITORING',
                'EXISTING_ALERT',
                'USER_INVESTIGATE',
                'CHAT_REQUEST'
            )
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("ai_investigations"):
        return
    op.execute(
        sa.text(
            """
            UPDATE ai_investigations
            SET trigger_type = metadata->>'legacyTriggerType',
                trigger_source = COALESCE(metadata->>'legacyTriggerSource', trigger_source),
                "trigger" = (COALESCE("trigger", '{}'::jsonb) - 'trigger_source')
                    || jsonb_build_object('trigger_type', metadata->>'legacyTriggerType'),
                metadata = metadata - 'legacyTriggerType' - 'legacyTriggerSource'
            WHERE metadata ? 'legacyTriggerType'
            """
        )
    )
