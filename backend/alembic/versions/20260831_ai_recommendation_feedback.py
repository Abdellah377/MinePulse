"""Operator decision and recommendation-discussion tables.

Revision ID: 20260831_ai_feedback
Revises: 20260831_haul_road_context
Create Date: 2026-08-31
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260831_ai_feedback"
down_revision: Union[str, None] = "20260831_haul_road_context"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("ai_investigations"):
        return
    if not inspector.has_table("ai_recommendation_decisions"):
        op.create_table(
            "ai_recommendation_decisions",
            sa.Column("decision_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("investigation_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("site_id", sa.BigInteger(), nullable=False),
            sa.Column("decision_type", sa.String(length=30), nullable=False),
            sa.Column("reason_category", sa.String(length=60), nullable=True),
            sa.Column("reason_text", sa.Text(), nullable=True),
            sa.Column("alternative_action", sa.Text(), nullable=True),
            sa.Column("original_recommendation", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("operator_action", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("actor_label", sa.String(length=120), nullable=True),
            sa.Column("context_tags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("outcome_status", sa.String(length=40), nullable=True),
            sa.Column("outcome_notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["investigation_id"],
                ["ai_investigations.investigation_id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(["site_id"], ["sites.site_id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("decision_id"),
            sa.UniqueConstraint("investigation_id"),
        )
        op.create_index(
            "idx_ai_recommendation_decisions_site_updated",
            "ai_recommendation_decisions",
            ["site_id", sa.text("updated_at DESC")],
        )
    if not inspector.has_table("ai_recommendation_discussion_messages"):
        op.create_table(
            "ai_recommendation_discussion_messages",
            sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("investigation_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("role", sa.String(length=20), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("actor_label", sa.String(length=120), nullable=True),
            sa.Column("cited_evidence_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["investigation_id"],
                ["ai_investigations.investigation_id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("message_id"),
        )
        op.create_index(
            "idx_ai_recommendation_discussion_investigation",
            "ai_recommendation_discussion_messages",
            ["investigation_id", sa.text("created_at ASC")],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("ai_recommendation_discussion_messages"):
        op.drop_table("ai_recommendation_discussion_messages")
    if inspector.has_table("ai_recommendation_decisions"):
        op.drop_table("ai_recommendation_decisions")
