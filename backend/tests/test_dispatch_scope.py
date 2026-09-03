from types import SimpleNamespace

from app.optimization.dispatch_scope import (
    APPLICABLE,
    NOT_APPLICABLE_TO_DISPATCH,
    assess_dispatch_scope,
    inbox_optimization_eligible,
)
from app.optimization.eligibility import NOT_APPLICABLE, OPTIMIZABLE, eligibility_for_alert
from app.optimization.solver import INSUFFICIENT_DATA, dispatch_outcome


def _trusted(**overrides):
    values = dict(
        truck=SimpleNamespace(equipment_id=1, code="TRK-018"),
        dest_code="DUMP_N",
        loaders=[SimpleNamespace(equipment_id=10, code="LDR-001")],
        loader_zones={10: "BANC_A"},
        roads=[{"id": "R-1", "status": "OPEN"}],
        planner_facts={"hasQueueCondition": False, "hasRoadRestrictionOrBlockage": False},
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def test_type_eligibility_still_marks_production_deviation_as_maybe_dispatch():
    assert eligibility_for_alert(SimpleNamespace(alert_type="PRODUCTION_DEVIATION", metadata_={})) == OPTIMIZABLE


def test_site_production_deviation_without_truck_is_not_applicable_to_dispatch():
    alert = SimpleNamespace(alert_type="PRODUCTION_DEVIATION", equipment_id=None, metadata_={})
    trusted = _trusted(truck=None, dest_code=None)
    assert assess_dispatch_scope(alert=alert, trusted=trusted) == NOT_APPLICABLE_TO_DISPATCH
    assert inbox_optimization_eligible(alert) is False


def test_congestion_with_authoritative_facts_is_applicable():
    alert = SimpleNamespace(alert_type="CONGESTION_RISK", equipment_id=1, metadata_={})
    assert assess_dispatch_scope(alert=alert, trusted=_trusted()) == APPLICABLE
    assert inbox_optimization_eligible(alert) is True


def test_production_deviation_with_queue_review_action_may_optimize():
    alert = SimpleNamespace(alert_type="PRODUCTION_DEVIATION", equipment_id=1, metadata_={})
    investigation = {
        "recommendation": {"action_type": "REVIEW_QUEUE_DISTRIBUTION", "description": "Rééquilibrer la file."},
        "conclusion": {"diagnosis_status": "PROBABLE"},
    }
    assert assess_dispatch_scope(alert=alert, trusted=_trusted(), investigation=investigation) == APPLICABLE


def test_production_deviation_maintenance_action_is_not_dispatch():
    alert = SimpleNamespace(alert_type="PRODUCTION_DEVIATION", equipment_id=1, metadata_={})
    investigation = {
        "recommendation": {"action_type": "ESCALATE_TO_MAINTENANCE", "description": "Isoler le concasseur."},
        "conclusion": {"diagnosis_status": "CONFIRMED"},
    }
    assert assess_dispatch_scope(alert=alert, trusted=_trusted(), investigation=investigation) == NOT_APPLICABLE_TO_DISPATCH


def test_production_deviation_inconclusive_without_queue_is_not_dispatch():
    alert = SimpleNamespace(alert_type="PRODUCTION_DEVIATION", equipment_id=1, metadata_={})
    investigation = {
        "recommendation": {"action_type": "CONTINUE_MONITORING", "description": "Preuve insuffisante."},
        "conclusion": {"diagnosis_status": "INCONCLUSIVE"},
    }
    assert assess_dispatch_scope(alert=alert, trusted=_trusted(), investigation=investigation) == NOT_APPLICABLE_TO_DISPATCH


def test_mechanical_alert_without_detector_is_type_not_applicable():
    alert = SimpleNamespace(alert_type="PREDICTED_MECHANICAL_FAILURE_RISK", equipment_id=7, metadata_={})
    assert eligibility_for_alert(alert) == NOT_APPLICABLE
    assert assess_dispatch_scope(alert=alert, trusted=_trusted()) == NOT_APPLICABLE
    assert inbox_optimization_eligible(alert) is False


def test_idle_wait_detector_with_truck_remains_applicable():
    alert = SimpleNamespace(
        alert_type="EQUIPMENT_ANOMALY",
        equipment_id=1,
        metadata_={"monitoring": {"detectorId": "prolonged-idle-wait"}},
    )
    assert assess_dispatch_scope(alert=alert, trusted=_trusted()) == APPLICABLE
    assert inbox_optimization_eligible(alert) is True


def test_road_closed_without_truck_can_still_be_inbox_eligible():
    alert = SimpleNamespace(alert_type="ROAD_CLOSED", equipment_id=None, metadata_={})
    assert inbox_optimization_eligible(alert) is True


def test_missing_metrics_on_a_real_dispatch_case_stay_insufficient_data():
    outcome, reason = dispatch_outcome(
        truck=SimpleNamespace(equipment_id=1, code="TRK-1"),
        dest="DUMP_N",
        candidates=[{"score": None, "travelMinutes": None, "waitMinutes": None}],
    )
    assert outcome == INSUFFICIENT_DATA
    assert reason != "Camion sujet inconnu"


def test_create_run_skips_solver_for_site_production_deviation(monkeypatch):
    from datetime import datetime, timezone

    from app.db.enums import AlertSeverity, AlertSource, AlertStatus
    from app.db.models import Alert, Site
    from app.optimization.service import create_optimization_run
    from app.services.operational.context import OperationalContext
    from test_workflow_hardening import WorkflowSession

    alert = Alert(
        alert_id=42,
        created_at=datetime(2026, 8, 31, 10, tzinfo=timezone.utc),
        occurred_at=datetime(2026, 8, 31, 10, tzinfo=timezone.utc),
        source=AlertSource.RULE,
        severity=AlertSeverity.WARNING,
        status=AlertStatus.NEW,
        alert_type="PRODUCTION_DEVIATION",
        title="écart",
        metadata_={},
        site_id=17,
        equipment_id=None,
    )
    session = WorkflowSession(alert)
    site = Site(site_id=17, code="SITE-17", name="Site", active=True)
    ctx = OperationalContext(
        site=site,
        shift=None,
        sim_now=datetime(2026, 8, 31, 12, tzinfo=timezone.utc),
        shift_window_start=datetime(2026, 8, 31, 6, tzinfo=timezone.utc),
        shift_window_end=datetime(2026, 8, 31, 14, tzinfo=timezone.utc),
    )

    def boom(*_a, **_k):
        raise AssertionError("generate_candidates must not run without dispatch scope")

    monkeypatch.setattr(
        "app.optimization.service.get_weather_context",
        lambda *_a, **_k: SimpleNamespace(
            status=SimpleNamespace(value="UNAVAILABLE"),
            unavailableReason="test",
            current=None,
        ),
    )
    monkeypatch.setattr("app.optimization.service.generate_candidates", boom)
    monkeypatch.setattr(
        "app.optimization.service.build_trusted_optimization_input",
        lambda *_a, **_k: SimpleNamespace(
            truck=None,
            dest_code=None,
            loaders=[],
            loader_zones={},
            roads=[],
            planner_facts={},
            snapshot_fields={},
            assignment=None,
            zone_codes={},
            loading={},
            origin_code=None,
            pending_commitments={},
            waiting_by_loader={},
            loader_service_minutes=None,
        ),
    )
    monkeypatch.setattr("app.optimization.service._investigation_bundle", lambda *_a, **_k: {
        "recommendation": {"description": "Vérifier le concasseur.", "action_type": "ESCALATE_TO_MAINTENANCE"},
        "conclusion": {"diagnosis_status": "CONFIRMED"},
    })
    payload = create_optimization_run(session, ctx, "alert-42")
    assert payload["outcome"] == NOT_APPLICABLE_TO_DISPATCH
    assert payload["candidates"] == []
    blob = str(payload)
    assert "Camion sujet inconnu" not in blob
    action = (payload.get("operatorRecommendedAction") or {})
    assert "Camion sujet inconnu" not in str(action.get("text") or "")

