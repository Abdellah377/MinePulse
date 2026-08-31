"""Separate follow-up status from the operator decision type.

Revision ID: 20260831_ai_follow_up
Revises: 20260831_ai_feedback
Create Date: 2026-08-31
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260831_ai_follow_up"
down_revision: Union[str, None] = "20260831_ai_feedback"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("ai_recommendation_decisions"):
        return
    existing = {column["name"] for column in inspector.get_columns("ai_recommendation_decisions")}
    if "follow_up_status" not in existing:
        op.add_column(
            "ai_recommendation_decisions",
            sa.Column("follow_up_status", sa.String(length=20), nullable=False, server_default="OPEN"),
        )
    op.execute(
        sa.text(
            """
            UPDATE ai_recommendation_decisions
            SET follow_up_status = 'RESOLVED',
                decision_type = CASE
                    WHEN operator_action IS NOT NULL THEN 'MODIFIED'
                    WHEN reason_category IS NOT NULL THEN 'REJECTED'
                    ELSE 'ACCEPTED'
                END
            WHERE decision_type = 'RESOLVED'
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("ai_recommendation_decisions"):
        return
    existing = {column["name"] for column in inspector.get_columns("ai_recommendation_decisions")}
    if "follow_up_status" not in existing:
        return
    op.execute(
        sa.text(
            """
            UPDATE ai_recommendation_decisions
            SET decision_type = 'RESOLVED'
            WHERE follow_up_status = 'RESOLVED'
            """
        )
    )
    op.drop_column("ai_recommendation_decisions", "follow_up_status")
