from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.ai.contracts import (
    DiscussionPostRequest,
    EvidenceItem,
    EvidenceKind,
    RecommendationDecisionRequest,
    RecommendationDecisionType,
    RecommendationDiscussionReply,
    RejectionReasonCategory,
)
from app.ai.discussion import post_discussion
from app.ai.feedback import (
    MAX_FEEDBACK_ITEMS,
    FeedbackConflict,
    conflicts_with_current_roads,
    extract_context_tags,
    extract_road_facts,
    get_decision_view,
    is_relevant_feedback,
    retrieve_operator_feedback,
    upsert_decision,
)
from app.db.models import AiInvestigation, AiRecommendationDecision, AiRecommendationDiscussionMessage
from app.db.database import get_db
from app.main import app


NOW = datetime(2026, 8, 31, 10, tzinfo=timezone.utc)
AI_ROOT = Path(__file__).resolve().parents[1] / "app" / "ai"
ROAD_EVIDENCE = {
    "originZoneId": "BANC_A",
    "destinationZoneId": "CRUSHER",
    "reachable": True,
    "excludedRoads": [{"id": "R-03", "status": "CLOSED", "reason": "BLASTING", "eligible": False}],
    "candidatePaths": [{"roadIds": ["R-05", "R-06"], "totalDistanceKm": 6.2, "estimatedTravelMinutes": 10.1}],
    "relevantRoads": [
        {"id": "R-03", "status": "CLOSED"},
        {"id": "R-05", "status": "OPEN"},
        {"id": "R-06", "status": "OPEN"},
    ],
}


class MemorySession:
    def __init__(self, investigation: AiInvestigation):
        self.investigation = investigation
        self.decision = None
        self.messages: list[AiRecommendationDiscussionMessage] = []
        self.llm_calls = 0

    def get(self, model, key):
        if model is AiInvestigation and key == self.investigation.investigation_id:
            return self.investigation
        return None

    def add(self, row):
        if isinstance(row, AiRecommendationDecision):
            self.decision = row
        elif isinstance(row, AiRecommendationDiscussionMessage):
            self.messages.append(row)

    def commit(self):
        return None

    def refresh(self, row):
        return None

    def execute(self, *args, **kwargs):
        raise AssertionError("decision/discussion must not query operational mutation tables")


def _investigation(*, site_id=1, recommendation=True, evidence=None):
    rec = {
        "action_type": "CONSIDER_REASSIGNMENT",
        "description": "Utiliser R-05 → R-06.",
        "rationale": "R-03 est fermée pour blasting.",
        "evidence_ids": ["ev-road"],
        "target_equipment_id": 14,
        "target_zone_id": None,
        "operational_constraints": [],
        "human_validation_required": True,
    }
    return AiInvestigation(
        investigation_id=uuid4(),
        created_at=NOW,
        updated_at=NOW,
        status="COMPLETED",
        trigger_type="CONGESTION_RISK",
        trigger_source="USER_INVESTIGATE",
        site_id=site_id,
        shift_id=2,
        equipment_id=14,
        zone_id=4,
        iteration_count=1,
        max_iterations=3,
        graph_version="1.3.0",
        provider="mock",
        model="mock",
        trigger_data={
            "trigger_type": "CONGESTION_RISK",
            "trigger_source": "USER_INVESTIGATE",
            "site_id": site_id,
            "shift_id": 2,
            "equipment_id": 14,
            "zone_id": 4,
            "occurred_at": NOW.isoformat(),
            "payload": {},
        },
        evidence=evidence
        or [
            {
                "evidence_id": "ev-road",
                "kind": "FACT",
                "source_tool": "road_network_context",
                "source_service": "app.services.operational.road_network.build_route_context",
                "metric": "road_network_context",
                "value": ROAD_EVIDENCE,
                "available": True,
                "status": "AVAILABLE",
                "source_record_ids": [],
                "metadata": {},
            }
        ],
        hypotheses=[],
        requested_information=[],
        contradictions=[],
        recommendation=rec if recommendation else None,
        conclusion={"summary": "R-03 closed", "diagnosis_status": "PROBABLE", "confidence": "MEDIUM"},
        metadata_={},
    )


def _wire(monkeypatch, session: MemorySession):
    monkeypatch.setattr("app.ai.feedback.get_investigation", lambda s, i: session.investigation)
    monkeypatch.setattr("app.ai.feedback.load_decision_row", lambda s, i: session.decision)
    monkeypatch.setattr("app.ai.discussion.get_investigation", lambda s, i: session.investigation)
    monkeypatch.setattr("app.ai.feedback.list_messages", lambda s, i: session.messages)
    monkeypatch.setattr("app.ai.discussion.list_messages", lambda s, i: session.messages)


def test_accept_reject_modify_persist_without_mutating_original(monkeypatch):
    inv = _investigation()
    session = MemorySession(inv)
    _wire(monkeypatch, session)
    original = dict(inv.recommendation)

    accepted = upsert_decision(
        session,
        inv.investigation_id,
        RecommendationDecisionRequest(decision_type=RecommendationDecisionType.ACCEPTED, actor_label="Chef A"),
    )
    assert accepted.decision_type == RecommendationDecisionType.ACCEPTED
    assert accepted.actor_label == "Chef A"
    assert accepted.original_recommendation["description"] == original["description"]
    assert session.decision.original_recommendation == original

    rejected = upsert_decision(
        session,
        inv.investigation_id,
        RecommendationDecisionRequest(
            decision_type=RecommendationDecisionType.REJECTED,
            reason_category=RejectionReasonCategory.CONTRAINTE_NON_CONNUE_PAR_IA,
            reason_text="R-05 est réservée aux camions légers pendant ce poste.",
            alternative_action="Maintenir TRK-014 au parking.",
            actor_label="Chef A",
        ),
    )
    assert rejected.decision_type == RecommendationDecisionType.REJECTED
    assert rejected.reason_text.startswith("R-05")
    assert rejected.alternative_action.startswith("Maintenir")
    assert session.decision.original_recommendation == original
    assert inv.recommendation == original

    modified = upsert_decision(
        session,
        inv.investigation_id,
        RecommendationDecisionRequest(
            decision_type=RecommendationDecisionType.MODIFIED,
            reason_category=RejectionReasonCategory.MEILLEURE_ALTERNATIVE,
            reason_text="Garder le parking 15 minutes.",
            alternative_action="Attendre la réouverture de R-03.",
        ),
    )
    assert modified.decision_type == RecommendationDecisionType.MODIFIED
    assert modified.operator_action["text"] == "Attendre la réouverture de R-03."
    assert session.decision.original_recommendation["description"] == original["description"]


def test_missing_recommendation_cannot_be_decided(monkeypatch):
    inv = _investigation(recommendation=False)
    session = MemorySession(inv)
    _wire(monkeypatch, session)
    try:
        upsert_decision(
            session,
            inv.investigation_id,
            RecommendationDecisionRequest(decision_type=RecommendationDecisionType.ACCEPTED),
        )
    except FeedbackConflict:
        pass
    else:
        raise AssertionError("expected conflict")


def test_site_scoping_and_pending_view(monkeypatch):
    inv = _investigation(site_id=7)
    session = MemorySession(inv)
    _wire(monkeypatch, session)
    view = get_decision_view(session, inv.investigation_id)
    assert view.decision_type == RecommendationDecisionType.PENDING
    assert view.decision is None
    record = upsert_decision(
        session,
        inv.investigation_id,
        RecommendationDecisionRequest(decision_type=RecommendationDecisionType.ACCEPTED),
    )
    assert record.site_id == 7


def test_feedback_modules_do_not_import_mutations_or_simulator():
    forbidden = (
        "app.services.operational.roads",
        "create_road",
        "update_road",
        "delete_road",
        "from simulator",
        "app.simulator",
    )
    for name in ("feedback.py", "discussion.py"):
        text = (AI_ROOT / name).read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"{name} contains {token}"


def test_accept_does_not_call_llm(monkeypatch):
    inv = _investigation()
    session = MemorySession(inv)
    _wire(monkeypatch, session)

    def boom(*args, **kwargs):
        raise AssertionError("decision persistence must not call the LLM")

    monkeypatch.setattr("app.ai.discussion.create_llm_provider", boom)
    monkeypatch.setattr("app.ai.llm.provider.create_llm_provider", boom)
    upsert_decision(
        session,
        inv.investigation_id,
        RecommendationDecisionRequest(
            decision_type=RecommendationDecisionType.REJECTED,
            reason_category=RejectionReasonCategory.AUTRE,
            reason_text="Pas maintenant",
        ),
    )


def test_discussion_without_generate_reply_does_not_call_llm(monkeypatch):
    inv = _investigation()
    session = MemorySession(inv)
    _wire(monkeypatch, session)

    def boom(*args, **kwargs):
        raise AssertionError("generate_reply=false must not call the LLM")

    monkeypatch.setattr("app.ai.discussion.create_llm_provider", boom)
    thread = post_discussion(
        session,
        inv.investigation_id,
        DiscussionPostRequest(content="Pourquoi ne pas utiliser R-07 ?", generate_reply=False),
    )
    assert len(thread.messages) == 1
    assert thread.messages[0].role.value == "OPERATOR"


def test_discussion_uses_persisted_recommendation_and_keeps_operator_input(monkeypatch):
    inv = _investigation()
    session = MemorySession(inv)
    _wire(monkeypatch, session)
    captured = {}

    class Provider:
        provider_name = "mock"
        model_name = "mock"
        def discuss_recommendation(self, payload):
            captured["payload"] = payload
            return RecommendationDiscussionReply(
                reply="R-07 est actuellement marquée CLOSED. Elle n’est pas admissible.",
                cited_evidence_ids=["ev-road", "invented"],
                operator_claims_unverified=["R-07 is usable"],
            )

    thread = post_discussion(
        session,
        inv.investigation_id,
        DiscussionPostRequest(content="Pourquoi ne pas utiliser R-07 ?", generate_reply=True),
        provider=Provider(),
    )
    assert captured["payload"]["recommendation"]["description"].startswith("Utiliser R-05")
    assert captured["payload"]["operatorMessageIsNotFact"] is True
    assert any(item["source_tool"] == "road_network_context" for item in captured["payload"]["evidence"])
    assert thread.messages[-1].role.value == "ASSISTANT"
    assert "invented" not in thread.messages[-1].cited_evidence_ids
    assert "ev-road" in thread.messages[-1].cited_evidence_ids
    dumped = str(thread.model_dump())
    assert "chain-of-thought" not in dumped
    assert "private" not in dumped


def test_retrieval_is_bounded_site_scoped_and_not_fact():
    current_status = {"R-06": "OPEN", "R-03": "CLOSED"}
    relevant = {
        "triggerType": "CONGESTION_RISK",
        "equipmentId": 14,
        "zoneId": 4,
        "actionType": "CONSIDER_REASSIGNMENT",
        "roadIds": ["R-08"],
        "roadStatus": {"R-06": "CLOSED"},
    }
    unrelated = {"triggerType": "CONNECTIVITY_ISSUE", "equipmentId": 99, "zoneId": 1, "roadIds": ["R-99"], "roadStatus": {}}
    assert is_relevant_feedback(relevant, trigger_type="CONGESTION_RISK", equipment_id=None, zone_id=None, road_ids=[], action_type=None)
    assert not is_relevant_feedback(unrelated, trigger_type="CONGESTION_RISK", equipment_id=14, zone_id=4, road_ids=["R-05"], action_type="INSPECT_EQUIPMENT")
    conflicts = conflicts_with_current_roads(relevant, current_status)
    assert conflicts[0]["roadId"] == "R-06"
    assert conflicts[0]["currentStatus"] == "OPEN"

    rows = []
    for index in range(8):
        rows.append(
            SimpleNamespace(
                decision_id=uuid4(),
                investigation_id=uuid4(),
                site_id=1,
                decision_type="REJECTED",
                reason_category="CONTRAINTE_NON_CONNUE_PAR_IA",
                reason_text=f"note-{index}",
                alternative_action=None,
                context_tags=relevant,
                updated_at=NOW,
            )
        )
    session = SimpleNamespace(execute=object())
    state = {
        "investigation_id": str(uuid4()),
        "trigger": SimpleNamespace(
            site_id=1,
            trigger_type="CONGESTION_RISK",
            equipment_id=14,
            zone_id=4,
        ),
        "evidence": [
            EvidenceItem(
                kind=EvidenceKind.FACT,
                source_tool="road_network_context",
                source_service="app.services.operational.road_network.build_route_context",
                metric="road_network_context",
                value=ROAD_EVIDENCE,
            )
        ],
        "recommendation": None,
    }

    import app.ai.feedback as feedback_mod

    original = feedback_mod.list_prior_decisions
    feedback_mod.list_prior_decisions = lambda *args, **kwargs: rows
    try:
        items = retrieve_operator_feedback(session, state)
    finally:
        feedback_mod.list_prior_decisions = original
    assert len(items) == MAX_FEEDBACK_ITEMS
    assert all(item.kind == EvidenceKind.OPERATOR_FEEDBACK for item in items)
    assert items[0].kind != EvidenceKind.FACT
    assert items[0].value["authoritativeFactsWin"] is True
    assert items[0].value["conflictsWithCurrentEvidence"][0]["currentStatus"] == "OPEN"


def test_closed_road_not_eligible_because_of_operator_preference():
    ids, status = extract_road_facts(
        [{"source_tool": "road_network_context", "value": ROAD_EVIDENCE}]
    )
    assert "R-03" in ids
    assert status["R-03"] == "CLOSED"
    assert status["R-05"] == "OPEN"
    tags = extract_context_tags(_investigation())
    assert "R-03" in tags["roadIds"]
    assert tags["roadStatus"]["R-03"] == "CLOSED"


def test_decision_api_routes_are_registered():
    paths = {route.path for route in app.routes}
    assert "/api/ai/investigations/{investigation_id}/decision" in paths
    assert "/api/ai/investigations/{investigation_id}/discussion" in paths


def test_put_decision_does_not_invoke_provider(monkeypatch):
    inv = _investigation()
    session = MemorySession(inv)
    _wire(monkeypatch, session)
    monkeypatch.setattr("app.ai.feedback.get_investigation", lambda s, i: inv)
    monkeypatch.setattr("app.ai.feedback.load_decision_row", lambda s, i: session.decision)
    app.dependency_overrides[get_db] = lambda: session
    monkeypatch.setattr(
        "app.ai.discussion.create_llm_provider",
        lambda: (_ for _ in ()).throw(AssertionError("LLM")),
    )
    try:
        response = TestClient(app).put(
            f"/api/ai/investigations/{inv.investigation_id}/decision",
            json={"decision_type": "ACCEPTED", "actor_label": "Chef"},
        )
        assert response.status_code == 200
        assert response.json()["decision_type"] == "ACCEPTED"
        assert response.json()["original_recommendation"]["description"] == inv.recommendation["description"]
    finally:
        app.dependency_overrides.pop(get_db, None)
