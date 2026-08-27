from datetime import date, datetime, time, timezone
from types import SimpleNamespace

from app.ai.contracts import EvidenceRequest, EvidenceRequestType, EvidenceStatus
from app.ai.tools import oem, operational
from app.ai.tools.registry import EvidenceToolRegistry
from app.db.models import Shift, Site
from app.services.operational.context import OperationalContext


def _context() -> OperationalContext:
    site = Site(site_id=1, code="SITE-A", name="Site A", active=True)
    shift = Shift(
        shift_id=2,
        site_id=1,
        name="Day",
        shift_date=date(2026, 8, 24),
        start_time=time(6),
        end_time=time(14),
    )
    return OperationalContext(
        site=site,
        shift=shift,
        sim_now=datetime(2026, 8, 24, 10, tzinfo=timezone.utc),
        shift_window_start=datetime(2026, 8, 24, 6, tzinfo=timezone.utc),
        shift_window_end=datetime(2026, 8, 24, 14, tzinfo=timezone.utc),
    )


def test_production_adapter_calls_authoritative_service(monkeypatch):
    called = []

    def fake_summary(session, ctx):
        called.append((session, ctx))
        return {
            "shiftly": [{"tonnage": 100.0, "target": None, "attainmentPct": None}],
            "hourly": [],
            "daily": [],
        }

    monkeypatch.setattr(operational.production_service, "production_summary", fake_summary)
    session = object()
    ctx = _context()

    evidence = operational.shift_production(session, ctx)

    assert called == [(session, ctx)]
    assert evidence.source_service == "app.services.operational.production.production_summary"
    assert evidence.value["shiftly"][0]["target"] is None
    assert evidence.value["shiftly"][0]["attainmentPct"] is None


def test_downtime_adapter_calls_authoritative_service(monkeypatch):
    monkeypatch.setattr(
        operational.downtime_service,
        "downtime_reasons",
        lambda session, ctx: [{"reason": "Maintenance", "hours": 1.5}],
    )

    evidence = operational.downtime(object(), _context())

    assert evidence.value == [{"reason": "Maintenance", "hours": 1.5}]
    assert evidence.source_service == "app.services.operational.downtime.downtime_reasons"


def test_unsupported_request_is_unavailable_and_never_executed():
    registry = EvidenceToolRegistry(SimpleNamespace())
    request = EvidenceRequest.model_construct(
        request_id="req-unsafe",
        request_type="ARBITRARY_SQL",
        equipment_id=None,
        zone_id=None,
        start_time=None,
        end_time=None,
        parameters=[],
        reason="try arbitrary query",
    )

    evidence = registry.dispatch(_context(), request)

    assert evidence.available is False
    assert evidence.value is None
    assert evidence.status == EvidenceStatus.UNSUPPORTED
    assert evidence.source_tool == "unsupported_evidence_request"


def test_request_contract_rejects_unknown_catalog_type():
    try:
        EvidenceRequest(request_type="ARBITRARY_SQL", reason="unsafe")
    except Exception as exc:
        assert "request_type" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("unknown request type should not validate")


def test_unexpected_service_exception_is_logged_and_safely_classified(monkeypatch, caplog):
    def fail_downtime(session, ctx):
        raise RuntimeError("internal database detail that must not reach evidence")

    monkeypatch.setattr(operational.downtime_service, "downtime_reasons", fail_downtime)
    registry = EvidenceToolRegistry(SimpleNamespace())
    request = EvidenceRequest(
        request_type=EvidenceRequestType.DOWNTIME,
        reason="Check downtime context",
    )

    with caplog.at_level("ERROR", logger="app.ai.tools.registry"):
        evidence = registry.dispatch(_context(), request)

    assert evidence.status == EvidenceStatus.ERROR
    assert evidence.available is False
    assert evidence.value is None
    assert "internal database detail" not in (evidence.notes or "")
    assert evidence.metadata["failureCategory"] == "SERVICE_ERROR"
    assert evidence.metadata["errorReference"].startswith("ai-tool-")
    record = next(record for record in caplog.records if record.message == "AI evidence service failed")
    assert record.tool_name == "downtime"
    assert record.request_id == request.request_id


def test_oem_diagnostics_reuses_existing_history_service_for_temporal_evidence(monkeypatch):
    monkeypatch.setattr(oem, "_equipment_code", lambda session, ctx, equipment_id: "TRK-001")
    monkeypatch.setattr(
        oem.queries,
        "diagnostic_parameters",
        lambda *args, **kwargs: [{"parameterKey": "oil_pressure_kpa", "min": 180}],
    )
    called = []

    def fake_history(*args, **kwargs):
        called.append((args, kwargs))
        return {
            "code": "TRK-001",
            "points": [
                {"ts": "2026-08-24T09:00:00+00:00", "oil_pressure_kpa": 410},
                {"ts": "2026-08-24T10:00:00+00:00", "oil_pressure_kpa": 180},
            ],
        }

    monkeypatch.setattr(oem.queries, "get_equipment_signal_history", fake_history)
    request = EvidenceRequest(
        request_type=EvidenceRequestType.OEM_DIAGNOSTICS,
        equipment_id=7,
        parameters=["oil_pressure_kpa"],
        reason="Inspect the pre-stop trend.",
    )

    evidence = oem.diagnostics(object(), _context(), request)

    assert called
    assert evidence.source_service == "app.oem.queries.diagnostic_parameters"
    assert evidence.metadata["signalHistory"]["points"][0]["oil_pressure_kpa"] == 410
    assert "scenario" not in evidence.model_dump_json().casefold()
