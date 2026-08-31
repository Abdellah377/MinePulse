"""Alert list indexes, optimization runs, and alert-keyed decisions.

Revision ID: 20260831_actions_opt
Revises: 20260831_ai_follow_up
Create Date: 2026-08-31
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260831_actions_opt"
down_revision: Union[str, None] = "20260831_ai_follow_up"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("alerts"):
        existing = {index["name"] for index in inspector.get_indexes("alerts")}
        if "ix_alerts_site_status" not in existing:
            op.create_index("ix_alerts_site_status", "alerts", ["site_id", "status"])
        op.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS ix_alerts_operational_time "
                "ON alerts ((COALESCE(occurred_at, created_at)) DESC, alert_id DESC)"
            )
        )
    if inspector.has_table("ai_recommendation_decisions"):
        columns = {column["name"] for column in inspector.get_columns("ai_recommendation_decisions")}
        if "alert_id" not in columns:
            op.add_column(
                "ai_recommendation_decisions",
                sa.Column("alert_id", sa.BigInteger(), nullable=True),
            )
            op.create_foreign_key(
                "fk_ai_recommendation_decisions_alert_id",
                "ai_recommendation_decisions",
                "alerts",
                ["alert_id"],
                ["alert_id"],
                ondelete="SET NULL",
            )
        op.execute(sa.text("ALTER TABLE ai_recommendation_decisions ALTER COLUMN investigation_id DROP NOT NULL"))
        op.execute(
            sa.text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_recommendation_decisions_alert_id "
                "ON ai_recommendation_decisions (alert_id) WHERE alert_id IS NOT NULL"
            )
        )
    if not inspector.has_table("ai_optimization_runs"):
        op.create_table(
            "ai_optimization_runs",
            sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("alert_id", sa.BigInteger(), nullable=False),
            sa.Column("site_id", sa.BigInteger(), nullable=False),
            sa.Column("optimizer_version", sa.String(length=40), nullable=False),
            sa.Column("weights", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("eligibility", sa.String(length=40), nullable=False),
            sa.Column("outcome", sa.String(length=40), nullable=False),
            sa.Column("snapshot_digest", sa.String(length=64), nullable=True),
            sa.Column("candidates", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("recommended_candidate_id", sa.String(length=80), nullable=True),
            sa.Column("weather_status", sa.String(length=40), nullable=True),
            sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["alert_id"], ["alerts.alert_id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["site_id"], ["sites.site_id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("run_id"),
        )
        op.create_index("ix_ai_optimization_runs_alert_created", "ai_optimization_runs", ["alert_id", "created_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("ai_optimization_runs"):
        op.drop_table("ai_optimization_runs")
    if inspector.has_table("ai_recommendation_decisions"):
        op.execute(sa.text("DROP INDEX IF EXISTS uq_ai_recommendation_decisions_alert_id"))
        columns = {column["name"] for column in inspector.get_columns("ai_recommendation_decisions")}
        if "alert_id" in columns:
            op.drop_constraint("fk_ai_recommendation_decisions_alert_id", "ai_recommendation_decisions", type_="foreignkey")
            op.drop_column("ai_recommendation_decisions", "alert_id")
    if inspector.has_table("alerts"):
        op.execute(sa.text("DROP INDEX IF EXISTS ix_alerts_operational_time"))
        existing = {index["name"] for index in inspector.get_indexes("alerts")}
        if "ix_alerts_site_status" in existing:
            op.drop_index("ix_alerts_site_status", table_name="alerts")
