from datetime import datetime
from decimal import Decimal
from uuid import UUID as PythonUUID, uuid4

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.enums import RecommendationStatus


class Prediction(Base):
    __tablename__ = "predictions"

    prediction_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False)
    prediction_for: Mapped[datetime] = mapped_column(nullable=False)
    prediction_type: Mapped[str] = mapped_column(String(120), nullable=False)
    equipment_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("equipment.equipment_id", ondelete="SET NULL")
    )
    zone_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("zones.zone_id", ondelete="SET NULL"))
    probability: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    predicted_value: Mapped[Decimal | None] = mapped_column(Numeric(16, 4))
    baseline_value: Mapped[Decimal | None] = mapped_column(Numeric(16, 4))
    impact_estimate_t: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    impact_estimate_tph: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    model_name: Mapped[str | None] = mapped_column(String(120))
    model_version: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="ACTIVE")
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)


class AiRecommendation(Base):
    __tablename__ = "ai_recommendations"

    recommendation_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(50), nullable=False)
    trigger_id: Mapped[int | None] = mapped_column(BigInteger)
    problem_summary: Mapped[str] = mapped_column(Text, nullable=False)
    action_type: Mapped[str] = mapped_column(String(120), nullable=False)
    action_description: Mapped[str] = mapped_column(Text, nullable=False)
    target_equipment_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("equipment.equipment_id", ondelete="SET NULL")
    )
    target_zone_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("zones.zone_id", ondelete="SET NULL"))
    expected_wait_reduction_min: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    expected_production_gain_tph: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    expected_cycle_reduction_min: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    status: Mapped[RecommendationStatus] = mapped_column(nullable=False, default=RecommendationStatus.GENERATED)
    assumptions: Mapped[dict] = mapped_column(JSONB, nullable=False, default=list)
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False, default=list)
    constraints: Mapped[dict] = mapped_column(JSONB, nullable=False, default=list)
    validated_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("operators.operator_id", ondelete="SET NULL"))
    validated_at: Mapped[datetime | None] = mapped_column()
    outcome_measured_at: Mapped[datetime | None] = mapped_column()
    actual_production_gain_tph: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    actual_wait_reduction_min: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)


class AiInvestigation(Base):
    """Durable audit record for a completed or failed investigation graph run."""

    __tablename__ = "ai_investigations"

    investigation_id: Mapped[PythonUUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(50), nullable=False)
    trigger_source: Mapped[str] = mapped_column(String(120), nullable=False)
    site_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sites.site_id", ondelete="CASCADE"), nullable=False
    )
    shift_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("shifts.shift_id", ondelete="SET NULL")
    )
    equipment_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("equipment.equipment_id", ondelete="SET NULL")
    )
    zone_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("zones.zone_id", ondelete="SET NULL")
    )
    iteration_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_iterations: Mapped[int] = mapped_column(Integer, nullable=False)
    graph_version: Mapped[str] = mapped_column(String(40), nullable=False)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    trigger_data: Mapped[dict] = mapped_column("trigger", JSONB, nullable=False)
    operational_context: Mapped[dict | None] = mapped_column(JSONB)
    evidence: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    hypotheses: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    requested_information: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    contradictions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    conclusion: Mapped[dict | None] = mapped_column(JSONB)
    recommendation: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[dict | None] = mapped_column(JSONB)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    debug_trace: Mapped[dict | None] = mapped_column(JSONB)


class AiRecommendationDecision(Base):
    """Operator response to an investigation recommendation. Does not mutate the original."""

    __tablename__ = "ai_recommendation_decisions"
    __table_args__ = (UniqueConstraint("investigation_id"),)

    decision_id: Mapped[PythonUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    investigation_id: Mapped[PythonUUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_investigations.investigation_id", ondelete="CASCADE"),
        nullable=False,
    )
    site_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sites.site_id", ondelete="CASCADE"), nullable=False
    )
    decision_type: Mapped[str] = mapped_column(String(30), nullable=False)
    reason_category: Mapped[str | None] = mapped_column(String(60))
    reason_text: Mapped[str | None] = mapped_column(Text)
    alternative_action: Mapped[str | None] = mapped_column(Text)
    original_recommendation: Mapped[dict] = mapped_column(JSONB, nullable=False)
    operator_action: Mapped[dict | None] = mapped_column(JSONB)
    actor_label: Mapped[str | None] = mapped_column(String(120))
    context_tags: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    outcome_status: Mapped[str | None] = mapped_column(String(40))
    outcome_notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AiRecommendationDiscussionMessage(Base):
    """Scoped recommendation discussion. Operator input is not operational fact."""

    __tablename__ = "ai_recommendation_discussion_messages"

    message_id: Mapped[PythonUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    investigation_id: Mapped[PythonUUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_investigations.investigation_id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    actor_label: Mapped[str | None] = mapped_column(String(120))
    cited_evidence_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
