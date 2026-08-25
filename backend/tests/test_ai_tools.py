from datetime import date, datetime, time, timezone
from types import SimpleNamespace

from app.ai.contracts import EvidenceRequest, EvidenceRequestType
from app.ai.tools import operational
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
    assert evidence.source_tool == "unsupported_evidence_request"


def test_request_contract_rejects_unknown_catalog_type():
    try:
        EvidenceRequest(request_type="ARBITRARY_SQL", reason="unsafe")
    except Exception as exc:
        assert "request_type" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("unknown request type should not validate")
