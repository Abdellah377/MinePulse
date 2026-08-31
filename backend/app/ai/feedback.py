"""Human-feedback memory: operator decisions and site-scoped retrieval.

Read-only toward operational systems. Does not mutate roads, assignments, or
hidden simulation state. Historical feedback is OPERATOR_FEEDBACK, never FACT.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.contracts import (
    DiscussionMessageRecord,
    DiscussionRole,
    DiscussionThread,
    EvidenceItem,
    EvidenceKind,
    FollowUpStatus,
    FollowUpStatusRequest,
    RecommendationDecisionRecord,
    RecommendationDecisionRequest,
    RecommendationDecisionType,
    RecommendationDecisionView,
    RejectionReasonCategory,
)
from app.ai.persistence import get_investigation
from app.db.models import AiInvestigation, AiRecommendationDecision, AiRecommendationDiscussionMessage

MAX_FEEDBACK_ITEMS = 5
MAX_RETRIEVAL_CANDIDATES = 40
_RECORDED_DECISIONS = frozenset(
    {
        RecommendationDecisionType.ACCEPTED.value,
        RecommendationDecisionType.MODIFIED.value,
        RecommendationDecisionType.REJECTED.value,
        "RESOLVED",  # legacy rows before follow_up_status existed
    }
)


class FeedbackNotFound(LookupError):
    """Investigation does not exist."""


class FeedbackConflict(RuntimeError):
    """Decision cannot be recorded (missing recommendation or invalid state)."""

    def __init__(self, message: str, code: str = "AI_RECOMMENDATION_REQUIRED"):
        super().__init__(message)
        self.code = code


def extract_road_facts(evidence: list | None) -> tuple[list[str], dict[str, str]]:
    road_ids: list[str] = []
    status_by_id: dict[str, str] = {}
    for item in evidence or []:
        if isinstance(item, EvidenceItem):
            tool = item.source_tool
            value = item.value
        elif isinstance(item, dict):
            tool = item.get("source_tool")
            value = item.get("value")
        else:
            continue
        if tool != "road_network_context" or not isinstance(value, dict):
            continue
        for key in ("relevantRoads", "excludedRoads"):
            for road in value.get(key) or []:
                if not isinstance(road, dict):
                    continue
                road_id = road.get("id") or road.get("roadId")
                if not road_id:
                    continue
                road_ids.append(str(road_id))
                status = road.get("status")
                if status:
                    status_by_id[str(road_id)] = str(status)
        for path in value.get("candidatePaths") or []:
            if isinstance(path, dict):
                for road_id in path.get("roadIds") or []:
                    road_ids.append(str(road_id))
    unique: list[str] = []
    seen: set[str] = set()
    for road_id in road_ids:
        if road_id in seen:
            continue
        seen.add(road_id)
        unique.append(road_id)
    return unique, status_by_id


def extract_context_tags(investigation: AiInvestigation) -> dict:
    rec = investigation.recommendation or {}
    road_ids, road_status = extract_road_facts(investigation.evidence)
    return {
        "triggerType": investigation.trigger_type,
        "actionType": rec.get("action_type"),
        "equipmentId": investigation.equipment_id,
        "zoneId": investigation.zone_id,
        "roadIds": road_ids,
        "roadStatus": road_status,
    }


def _enum_or_none(cls, value):
    if value is None:
        return None
    return cls(value) if not isinstance(value, cls) else value


def recorded_decision_type(row) -> RecommendationDecisionType:
    """Operator decision only. Legacy RESOLVED rows are remapped, never returned as RESOLVED."""
    raw = getattr(row, "decision_type", None)
    if raw == "RESOLVED":
        if getattr(row, "operator_action", None):
            return RecommendationDecisionType.MODIFIED
        if getattr(row, "reason_category", None):
            return RecommendationDecisionType.REJECTED
        return RecommendationDecisionType.ACCEPTED
    return RecommendationDecisionType(raw)


def recorded_follow_up_status(row) -> FollowUpStatus:
    raw = getattr(row, "follow_up_status", None)
    if raw:
        return FollowUpStatus(raw)
    if getattr(row, "decision_type", None) == "RESOLVED":
        return FollowUpStatus.RESOLVED
    return FollowUpStatus.OPEN


def to_decision_record(row: AiRecommendationDecision) -> RecommendationDecisionRecord:
    return RecommendationDecisionRecord(
        decision_id=row.decision_id,
        investigation_id=row.investigation_id,
        alert_id=getattr(row, "alert_id", None),
        site_id=row.site_id,
        decision_type=recorded_decision_type(row),
        follow_up_status=recorded_follow_up_status(row),
        reason_category=_enum_or_none(RejectionReasonCategory, row.reason_category),
        reason_text=row.reason_text,
        alternative_action=row.alternative_action,
        original_recommendation=row.original_recommendation or {},
        operator_action=row.operator_action,
        actor_label=row.actor_label,
        context_tags=row.context_tags or {},
        outcome_status=row.outcome_status,
        outcome_notes=row.outcome_notes,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def load_decision_row(session: Session, investigation_id: UUID) -> AiRecommendationDecision | None:
    return session.scalar(
        select(AiRecommendationDecision).where(
            AiRecommendationDecision.investigation_id == investigation_id
        )
    )


def load_decision_row_for_alert(session: Session, alert_id: int) -> AiRecommendationDecision | None:
    return session.scalar(
        select(AiRecommendationDecision).where(AiRecommendationDecision.alert_id == alert_id)
    )


def _alert_id_from_investigation(investigation: AiInvestigation) -> int | None:
    trigger = investigation.trigger_data or {}
    raw = str(trigger.get("source_record_id") or "")
    if raw.startswith("alert-"):
        raw = raw[6:]
    try:
        return int(raw)
    except ValueError:
        return None


def get_decision_view(session: Session, investigation_id: UUID) -> RecommendationDecisionView:
    investigation = get_investigation(session, investigation_id)
    if investigation is None:
        raise FeedbackNotFound("investigation")
    row = load_decision_row(session, investigation_id)
    if row is None:
        return RecommendationDecisionView(
            investigation_id=investigation_id,
            decision_type=RecommendationDecisionType.PENDING,
            follow_up_status=None,
            decision=None,
        )
    record = to_decision_record(row)
    return RecommendationDecisionView(
        investigation_id=investigation_id,
        decision_type=record.decision_type,
        follow_up_status=record.follow_up_status,
        decision=record,
    )


def upsert_decision(
    session: Session,
    investigation_id: UUID,
    request: RecommendationDecisionRequest,
) -> RecommendationDecisionRecord:
    investigation = get_investigation(session, investigation_id)
    if investigation is None:
        raise FeedbackNotFound("investigation")
    if not investigation.recommendation:
        raise FeedbackConflict("recommendation missing")
    now = datetime.now(timezone.utc)
    row = load_decision_row(session, investigation_id)
    operator_action = None
    if request.decision_type == RecommendationDecisionType.MODIFIED:
        operator_action = {
            "text": request.alternative_action or request.reason_text or "",
        }
    if row is None:
        row = AiRecommendationDecision(
            decision_id=uuid4(),
            investigation_id=investigation.investigation_id,
            alert_id=_alert_id_from_investigation(investigation),
            site_id=investigation.site_id,
            original_recommendation=dict(investigation.recommendation),
            context_tags=extract_context_tags(investigation),
            created_at=now,
            updated_at=now,
            decision_type=request.decision_type.value,
            follow_up_status=FollowUpStatus.OPEN.value,
        )
        session.add(row)
    row.updated_at = now
    row.decision_type = request.decision_type.value
    row.reason_category = request.reason_category.value if request.reason_category else None
    row.reason_text = request.reason_text
    row.alternative_action = request.alternative_action
    row.operator_action = operator_action
    row.actor_label = request.actor_label
    if not getattr(row, "follow_up_status", None):
        row.follow_up_status = FollowUpStatus.OPEN.value
    if not row.original_recommendation:
        row.original_recommendation = dict(investigation.recommendation)
    if not row.context_tags:
        row.context_tags = extract_context_tags(investigation)
    session.commit()
    session.refresh(row)
    return to_decision_record(row)


def upsert_alert_decision(
    session: Session,
    alert_id: int,
    request: RecommendationDecisionRequest,
    *,
    site_id: int,
    original_recommendation: dict,
    investigation_id: UUID | None = None,
) -> RecommendationDecisionRecord:
    now = datetime.now(timezone.utc)
    row = load_decision_row_for_alert(session, alert_id)
    if row is None and investigation_id is not None:
        row = load_decision_row(session, investigation_id)
    operator_action = None
    if request.decision_type == RecommendationDecisionType.MODIFIED:
        operator_action = {"text": request.alternative_action or request.reason_text or ""}
    if row is None:
        row = AiRecommendationDecision(
            decision_id=uuid4(),
            investigation_id=investigation_id,
            alert_id=alert_id,
            site_id=site_id,
            original_recommendation=dict(original_recommendation),
            context_tags={},
            created_at=now,
            updated_at=now,
            decision_type=request.decision_type.value,
            follow_up_status=FollowUpStatus.OPEN.value,
        )
        session.add(row)
    row.updated_at = now
    row.alert_id = alert_id
    if investigation_id is not None:
        row.investigation_id = investigation_id
    row.decision_type = request.decision_type.value
    row.reason_category = request.reason_category.value if request.reason_category else None
    row.reason_text = request.reason_text
    row.alternative_action = request.alternative_action
    row.operator_action = operator_action
    row.actor_label = request.actor_label
    if not getattr(row, "follow_up_status", None):
        row.follow_up_status = FollowUpStatus.OPEN.value
    if not row.original_recommendation:
        row.original_recommendation = dict(original_recommendation)
    session.commit()
    session.refresh(row)
    return to_decision_record(row)


def set_follow_up_status(
    session: Session,
    investigation_id: UUID,
    request: FollowUpStatusRequest,
) -> RecommendationDecisionRecord:
    investigation = get_investigation(session, investigation_id)
    if investigation is None:
        raise FeedbackNotFound("investigation")
    row = load_decision_row(session, investigation_id)
    if row is None:
        raise FeedbackConflict("decision missing", code="AI_DECISION_REQUIRED")
    if row.decision_type == "RESOLVED":
        row.decision_type = recorded_decision_type(row).value
    row.follow_up_status = request.follow_up_status.value
    row.updated_at = datetime.now(timezone.utc)
    session.commit()
    session.refresh(row)
    return to_decision_record(row)


def list_messages(session: Session, investigation_id: UUID) -> list[AiRecommendationDiscussionMessage]:
    return list(
        session.scalars(
            select(AiRecommendationDiscussionMessage)
            .where(AiRecommendationDiscussionMessage.investigation_id == investigation_id)
            .order_by(AiRecommendationDiscussionMessage.created_at.asc())
        )
    )


def get_discussion(session: Session, investigation_id: UUID) -> DiscussionThread:
    investigation = get_investigation(session, investigation_id)
    if investigation is None:
        raise FeedbackNotFound("investigation")
    return DiscussionThread(
        investigation_id=investigation_id,
        messages=[_to_message(row) for row in list_messages(session, investigation_id)],
    )


def add_message(
    session: Session,
    investigation_id: UUID,
    *,
    role: DiscussionRole,
    content: str,
    actor_label: str | None = None,
    cited_evidence_ids: list[str] | None = None,
) -> DiscussionMessageRecord:
    investigation = get_investigation(session, investigation_id)
    if investigation is None:
        raise FeedbackNotFound("investigation")
    row = AiRecommendationDiscussionMessage(
        message_id=uuid4(),
        investigation_id=investigation_id,
        role=role.value,
        content=content,
        actor_label=actor_label,
        cited_evidence_ids=list(cited_evidence_ids or []),
        created_at=datetime.now(timezone.utc),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return _to_message(row)


def _to_message(row: AiRecommendationDiscussionMessage) -> DiscussionMessageRecord:
    return DiscussionMessageRecord(
        message_id=row.message_id,
        investigation_id=row.investigation_id,
        role=DiscussionRole(row.role),
        content=row.content,
        actor_label=row.actor_label,
        cited_evidence_ids=list(row.cited_evidence_ids or []),
        created_at=row.created_at,
    )


def list_prior_decisions(
    session: Session,
    *,
    site_id: int,
    exclude_investigation_id: UUID | None,
) -> list[AiRecommendationDecision]:
    query = select(AiRecommendationDecision).where(
        AiRecommendationDecision.site_id == site_id,
        AiRecommendationDecision.decision_type.in_(_RECORDED_DECISIONS),
    )
    if exclude_investigation_id is not None:
        query = query.where(AiRecommendationDecision.investigation_id != exclude_investigation_id)
    return list(
        session.scalars(
            query.order_by(AiRecommendationDecision.updated_at.desc()).limit(MAX_RETRIEVAL_CANDIDATES)
        )
    )


def is_relevant_feedback(
    tags: dict,
    *,
    trigger_type: str | None,
    equipment_id: int | None,
    zone_id: int | None,
    road_ids: list[str],
    action_type: str | None,
) -> bool:
    if trigger_type and tags.get("triggerType") == trigger_type:
        return True
    if equipment_id is not None and tags.get("equipmentId") == equipment_id:
        return True
    if zone_id is not None and tags.get("zoneId") == zone_id:
        return True
    if action_type and tags.get("actionType") == action_type:
        return True
    historic_roads = {str(item) for item in (tags.get("roadIds") or [])}
    if historic_roads and historic_roads & set(road_ids):
        return True
    return False


def conflicts_with_current_roads(tags: dict, current_status: dict[str, str]) -> list[dict]:
    conflicts: list[dict] = []
    historic = tags.get("roadStatus") or {}
    if not isinstance(historic, dict):
        return conflicts
    for road_id, previous in historic.items():
        current = current_status.get(str(road_id))
        if current and previous and str(current) != str(previous):
            conflicts.append(
                {
                    "roadId": str(road_id),
                    "historicalStatus": str(previous),
                    "currentStatus": str(current),
                }
            )
    return conflicts


def retrieve_operator_feedback(session, state) -> list[EvidenceItem]:
    """Bounded site memory for the recommendation step. Never classified as FACT."""
    if session is None or not hasattr(session, "execute"):
        return []
    trigger = state.get("trigger")
    if trigger is None:
        return []
    try:
        investigation_id = UUID(str(state.get("investigation_id")))
    except (TypeError, ValueError):
        return []
    road_ids, current_status = extract_road_facts(state.get("evidence") or [])
    try:
        rows = list_prior_decisions(
            session,
            site_id=trigger.site_id,
            exclude_investigation_id=investigation_id,
        )
    except Exception:
        return []
    rec = state.get("recommendation")
    action_type = getattr(rec, "action_type", None)
    action_value = getattr(action_type, "value", action_type)
    selected: list[EvidenceItem] = []
    for row in rows:
        tags = row.context_tags or {}
        if not is_relevant_feedback(
            tags,
            trigger_type=getattr(trigger.trigger_type, "value", trigger.trigger_type),
            equipment_id=trigger.equipment_id,
            zone_id=trigger.zone_id,
            road_ids=road_ids,
            action_type=action_value,
        ):
            continue
        conflicts = conflicts_with_current_roads(tags, current_status)
        selected.append(
            EvidenceItem(
                kind=EvidenceKind.OPERATOR_FEEDBACK,
                source_tool="operator_feedback_memory",
                source_service="app.ai.feedback.retrieve_operator_feedback",
                metric="site_decision_history",
                value={
                    "decisionType": recorded_decision_type(row).value,
                    "followUpStatus": recorded_follow_up_status(row).value,
                    "reasonCategory": row.reason_category,
                    "reasonText": row.reason_text,
                    "alternativeAction": row.alternative_action,
                    "contextTags": tags,
                    "conflictsWithCurrentEvidence": conflicts,
                    "authoritativeFactsWin": True,
                },
                site_id=row.site_id,
                equipment_id=tags.get("equipmentId") if isinstance(tags.get("equipmentId"), int) else None,
                zone_id=tags.get("zoneId") if isinstance(tags.get("zoneId"), int) else None,
                observed_at=row.updated_at,
                source_record_ids=[f"decision:{row.decision_id}", f"investigation:{row.investigation_id}"],
                metadata={
                    "knowledgeClass": "OPERATOR_FEEDBACK",
                    "notOperationalFact": True,
                    "conflictsWithCurrentEvidence": conflicts,
                },
                notes=(
                    "Historical operator decision at this site. Contextual only; "
                    "may be stale or subjective. Current operational facts take precedence."
                ),
            )
        )
        if len(selected) >= MAX_FEEDBACK_ITEMS:
            break
    return selected
