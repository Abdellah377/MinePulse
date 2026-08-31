from datetime import date, datetime, time, timedelta, timezone
from types import SimpleNamespace

from app.ai.contracts import (
    EvidenceItem,
    EvidenceKind,
    EvidenceRequest,
    EvidenceRequestType,
    EvidenceStatus,
    InvestigationSubject,
    InvestigationTrigger,
    TriggerSource,
    TriggerType,
)
from app.ai.tools import oem, operational
from app.ai.tools.registry import EvidenceToolRegistry
from app.db.models import Shift, Site
from app.services.operational.context import OperationalContext
from app.services.operational.loading import summarize_loading_durations


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


def test_loading_context_adapter_calls_authoritative_service_and_preserves_bounds(monkeypatch):
    captured = []

    def fake_context(session, ctx, *, equipment_id=None, zone_id=None):
        captured.append((session, ctx, equipment_id, zone_id))
        return {
            "siteId": ctx.site_id,
            "shiftId": ctx.shift_id,
            "windowStart": ctx.shift_window_start,
            "windowEnd": ctx.sim_now,
            "targetEquipmentId": equipment_id,
            "targetZoneId": zone_id,
            "loaders": [{"loaderId": 10, "waitingTruckCount": 3}],
            "bounds": {"maxLoaders": 6, "maxWaitingTrucksPerLoader": 8},
            "sourceRecordIds": ["assignment:1", "state:2"],
        }

    monkeypatch.setattr(operational.loading_service, "loading_service_context", fake_context)
    evidence = operational.loading_context(object(), _context(), equipment_id=7, zone_id=3)

    assert captured and captured[0][2:] == (7, 3)
    assert evidence.source_service == "app.services.operational.loading.loading_service_context"
    assert evidence.value["loaders"][0]["waitingTruckCount"] == 3
    assert evidence.source_record_ids == ["assignment:1", "state:2"]
    assert "scenario" not in evidence.model_dump_json().casefold()


def test_loading_duration_summary_is_bounded_and_null_aware():
    samples = [
        {
            "endTime": f"2026-08-24T09:{index:02d}:00+00:00",
            "durationMinutes": float(index),
        }
        for index in range(1, 16)
    ]
    summary = summarize_loading_durations(samples)

    assert summary["recentSampleCount"] == 3
    assert summary["baselineSampleCount"] == 8
    assert summary["recentAverageLoadingMinutes"] == 14.0
    assert summary["baselineAverageLoadingMinutes"] == 8.5
    assert summarize_loading_durations([])["loadingDurationChangePct"] is None


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


def test_trend_service_summarizes_and_downsamples_without_coercing_missing_to_zero(monkeypatch):
    points = [
        {
            "ts": f"2026-08-24T09:{index:02d}:00+00:00",
            "oil_pressure_kpa": 420 - index * 10,
            "fuel_rate_lph": None,
        }
        for index in range(20)
    ]
    monkeypatch.setattr(
        oem.queries,
        "get_equipment_signal_history",
        lambda *args, **kwargs: {
            "code": "TRK-001",
            "type": "truck",
            "from": "2026-08-24T09:00:00+00:00",
            "to": "2026-08-24T09:19:00+00:00",
            "bucketSec": 10,
            "signals": [
                {"key": "oil_pressure_kpa", "unit": "kPa"},
                {"key": "fuel_rate_lph", "unit": "l/h"},
            ],
            "points": points,
            "unavailable": [],
            "empty": False,
        },
    )

    result = oem.queries.get_equipment_signal_trends(
        object(),
        "TRK-001",
        None,
        None,
        ["oil_pressure_kpa", "fuel_rate_lph"],
        site_id=1,
    )

    oil, fuel = result["metrics"]
    assert oil["direction"] == "falling"
    assert oil["firstValue"] == 420
    assert oil["lastValue"] == 230
    assert len(oil["representativeSamples"]) == 8
    assert [sample["ts"] for sample in oil["representativeSamples"]] == sorted(
        sample["ts"] for sample in oil["representativeSamples"]
    )
    assert fuel["sampleCount"] == 0
    assert fuel["firstValue"] is None
    assert fuel["direction"] == "insufficient_data"


def test_ai_telemetry_trend_adapter_has_bounded_incident_provenance_and_no_hidden_truth(monkeypatch):
    monkeypatch.setattr(oem, "_equipment_code", lambda session, ctx, equipment_id: "TRK-001")
    captured = {}

    def fake_trends(*args, **kwargs):
        captured["args"] = args
        return {
            "code": "TRK-001",
            "from": args[2],
            "to": args[3],
            "metrics": [
                {
                    "metric": "oil_pressure_kpa",
                    "unit": "kPa",
                    "sampleCount": 5,
                    "firstObservedAt": args[2],
                    "lastObservedAt": args[3],
                    "firstValue": 410,
                    "lastValue": 275,
                    "direction": "falling",
                    "representativeSamples": [],
                }
            ],
            "sourcePointCount": 5,
            "empty": False,
        }

    monkeypatch.setattr(oem.queries, "get_equipment_signal_trends", fake_trends)
    incident = _context().sim_now - timedelta(minutes=2)
    request = EvidenceRequest(
        request_type=EvidenceRequestType.EQUIPMENT_TELEMETRY_TRENDS,
        equipment_id=7,
        end_time=incident,
        parameters=["mechanical"],
        reason="Inspect pre-incident telemetry.",
    )

    evidence = oem.telemetry_trends(object(), _context(), request)

    assert evidence.available
    assert evidence.source_service == "app.oem.queries.get_equipment_signal_trends"
    assert evidence.equipment_id == 7
    assert datetime.fromisoformat(evidence.metadata["windowEnd"].replace("Z", "+00:00")) == incident
    assert evidence.metadata["metricCount"] == 1
    assert evidence.source_record_ids == ["equipment:7"]
    assert "scenario" not in evidence.model_dump_json().casefold()
    assert "root_cause" not in evidence.model_dump_json().casefold()


def test_preincident_count_compares_timezone_offsets_as_datetimes(monkeypatch):
    monkeypatch.setattr(oem, "_equipment_code", lambda session, ctx, equipment_id: "TRK-001")
    monkeypatch.setattr(
        oem.queries,
        "get_equipment_signal_trends",
        lambda *args, **kwargs: {
            "code": "TRK-001",
            "metrics": [
                {
                    "metric": "oil_pressure_kpa",
                    "sampleCount": 5,
                    "lastObservedAt": "2026-08-24T10:00:00+01:00",
                }
            ],
            "sourcePointCount": 5,
            "empty": False,
        },
    )
    request = EvidenceRequest(
        request_type=EvidenceRequestType.EQUIPMENT_TELEMETRY_TRENDS,
        equipment_id=7,
        end_time=datetime(2026, 8, 24, 9, 0, tzinfo=timezone.utc),
        parameters=["mechanical"],
        reason="Verify timezone-normalized temporal support.",
    )

    evidence = oem.telemetry_trends(object(), _context(), request)

    assert evidence.metadata["preIncidentSampleCount"] == 5


def test_equipment_investigation_initial_evidence_includes_telemetry_trends(monkeypatch):
    captured = []

    def fake_safe(self, ctx, name, call, **kwargs):
        captured.append(name)
        if name == "equipment_telemetry_trends":
            return call()
        return EvidenceItem(
            kind=EvidenceKind.FACT,
            source_tool=name,
            source_service="test",
            metric=name,
            value={},
        )

    monkeypatch.setattr(EvidenceToolRegistry, "_safe_call", fake_safe)
    monkeypatch.setattr(
        oem,
        "telemetry_trends",
        lambda session, ctx, request: EvidenceItem(
            kind=EvidenceKind.DERIVED_METRIC,
            source_tool="equipment_telemetry_trends",
            source_service="app.oem.queries.get_equipment_signal_trends",
            metric="equipment_telemetry_trends",
            value={"metrics": []},
            equipment_id=request.equipment_id,
            metadata={"incidentTime": request.end_time.isoformat()},
        ),
    )
    incident = _context().sim_now - timedelta(minutes=1)
    trigger = InvestigationTrigger(
        trigger_type=TriggerType.EQUIPMENT_ANOMALY,
        trigger_source=TriggerSource.USER_INVESTIGATE,
        site_id=1,
        shift_id=2,
        equipment_id=7,
        occurred_at=incident,
    )

    evidence = EvidenceToolRegistry(object()).gather_initial(_context(), trigger)

    trend = next(item for item in evidence if item.source_tool == "equipment_telemetry_trends")
    assert "equipment_telemetry_trends" in captured
    assert datetime.fromisoformat(trend.metadata["incidentTime"].replace("Z", "+00:00")) == incident


def test_congestion_initial_evidence_includes_cross_asset_loading_context(monkeypatch):
    captured = []

    def fake_safe(self, ctx, name, call, **kwargs):
        captured.append(name)
        return EvidenceItem(
            kind=EvidenceKind.FACT,
            source_tool=name,
            source_service="test",
            metric=name,
            value={},
        )

    monkeypatch.setattr(EvidenceToolRegistry, "_safe_call", fake_safe)
    trigger = InvestigationTrigger(
        trigger_type=TriggerType.OPERATIONAL_EVENT,
        trigger_source=TriggerSource.USER_INVESTIGATE,
        site_id=1,
        shift_id=2,
        equipment_id=7,
        occurred_at=_context().sim_now,
        payload={"reason": "TRK-007 waits for loading."},
    )

    EvidenceToolRegistry(object()).gather_initial(_context(), trigger)

    assert "loading_context" in captured
    assert "equipment_timeline" in captured


def test_fuel_trigger_selects_bounded_fuel_metric_group(monkeypatch):
    requests = []

    def fake_safe(self, ctx, name, call, **kwargs):
        if name == "equipment_telemetry_trends":
            return call()
        return EvidenceItem(
            kind=EvidenceKind.FACT,
            source_tool=name,
            source_service="test",
            metric=name,
            value={},
        )

    monkeypatch.setattr(EvidenceToolRegistry, "_safe_call", fake_safe)
    monkeypatch.setattr(
        oem,
        "telemetry_trends",
        lambda session, ctx, request: requests.append(request) or EvidenceItem(
            kind=EvidenceKind.DERIVED_METRIC,
            source_tool="equipment_telemetry_trends",
            source_service="test",
            metric="equipment_telemetry_trends",
            value={},
        ),
    )
    trigger = InvestigationTrigger(
        trigger_type=TriggerType.EQUIPMENT_ANOMALY,
        trigger_source=TriggerSource.EXISTING_ALERT,
        site_id=1,
        equipment_id=7,
        occurred_at=_context().sim_now,
        payload={"title": "Fuel Rate High"},
    )

    EvidenceToolRegistry(object()).gather_initial(_context(), trigger)

    assert requests[0].parameters == ["fuel"]


def test_predicted_mechanical_failure_risk_uses_mechanical_evidence_and_model_prediction(monkeypatch):
    captured = []
    requests = []

    def fake_safe(self, ctx, name, call, **kwargs):
        captured.append(name)
        if name == "equipment_telemetry_trends":
            return call()
        return EvidenceItem(
            kind=EvidenceKind.FACT,
            source_tool=name,
            source_service="test",
            metric=name,
            value={},
        )

    monkeypatch.setattr(EvidenceToolRegistry, "_safe_call", fake_safe)
    monkeypatch.setattr(
        oem,
        "telemetry_trends",
        lambda session, ctx, request: requests.append(request) or EvidenceItem(
            kind=EvidenceKind.DERIVED_METRIC,
            source_tool="equipment_telemetry_trends",
            source_service="test",
            metric="equipment_telemetry_trends",
            value={},
        ),
    )
    trigger = InvestigationTrigger(
        trigger_type=TriggerType.PREDICTED_MECHANICAL_FAILURE_RISK,
        trigger_source=TriggerSource.AUTOMATIC_MONITORING,
        site_id=1,
        shift_id=2,
        equipment_id=7,
        occurred_at=_context().sim_now,
        payload={
            "value": 0.72,
            "threshold": 0.41,
            "context": {
                "horizonMinutes": 60,
                "modelVersion": "failure_risk_v1",
                "modelType": "logistic",
                "dataClass": "synthetic_prototype",
                "source": "FAILURE_RISK_V1",
                "riskLevel": "HIGH",
            },
        },
    )

    evidence = EvidenceToolRegistry(object()).gather_initial(_context(), trigger)

    assert trigger.subject == InvestigationSubject.MAINTENANCE
    prediction = next(item for item in evidence if item.kind == EvidenceKind.MODEL_PREDICTION)
    assert prediction.metric == "failure_risk_probability"
    assert prediction.value == 0.72
    assert prediction.metadata["dataClass"] == "synthetic_prototype"
    assert prediction.metadata["source"] == "FAILURE_RISK_V1"
    assert "not a confirmed failure" in prediction.notes.casefold()
    assert requests[0].parameters == ["mechanical"]
    assert "equipment_telemetry_trends" in captured
    assert "road_network_context" not in captured


def _haul_catalog():
    return [
        {
            "id": "R-03",
            "name": "R-03",
            "fromZoneId": "BANC_A",
            "toZoneId": "CRUSHER",
            "status": "CLOSED",
            "distanceKm": 4.2,
            "speedLimitKmh": 35,
            "description": None,
            "statusReason": "BLASTING",
            "statusNote": None,
            "points": [{"x": 0, "y": 0}],
        },
        {
            "id": "R-05",
            "name": "R-05",
            "fromZoneId": "BANC_A",
            "toZoneId": "PARKING",
            "status": "OPEN",
            "distanceKm": 3.4,
            "speedLimitKmh": 38,
            "description": None,
            "statusReason": None,
            "statusNote": None,
        },
        {
            "id": "R-06",
            "name": "R-06",
            "fromZoneId": "PARKING",
            "toZoneId": "CRUSHER",
            "status": "OPEN",
            "distanceKm": 2.8,
            "speedLimitKmh": 35,
            "description": None,
            "statusReason": None,
            "statusNote": None,
        },
    ]


def test_road_network_context_is_approved_fact_evidence(monkeypatch):
    zones = {
        1: SimpleNamespace(zone_id=1, code="BANC_A", name="Banc A", type="PIT", description="loading face"),
        2: SimpleNamespace(zone_id=2, code="CRUSHER", name="Crusher", type="CRUSHER", description=None),
        3: SimpleNamespace(zone_id=3, code="PARKING", name="Parking", type="PARKING", description=None),
    }
    monkeypatch.setattr(
        operational.road_catalog,
        "list_road_catalog",
        lambda session, ctx: (_haul_catalog(), zones),
    )
    monkeypatch.setattr(
        operational.road_catalog,
        "resolve_haul_endpoints",
        lambda *args, **kwargs: ("BANC_A", "CRUSHER"),
    )

    evidence = operational.road_network_context(object(), _context(), equipment_id=7)

    assert EvidenceRequestType.ROAD_NETWORK_CONTEXT.value == "ROAD_NETWORK_CONTEXT"
    assert evidence.kind == EvidenceKind.FACT
    assert evidence.source_tool == "road_network_context"
    assert evidence.source_service == "app.services.operational.road_network.build_route_context"
    assert evidence.available is True
    assert evidence.value["reachable"] is True
    assert evidence.value["candidatePaths"][0]["roadIds"] == ["R-05", "R-06"]
    assert evidence.value["candidatePaths"][0]["totalDistanceKm"] == 6.2
    assert len(evidence.value["candidatePaths"]) <= 2
    assert evidence.value["zoneDescriptionIsNotARoutingRule"] is True
    blob = evidence.model_dump_json()
    assert "geometry" not in blob
    assert '"points"' not in blob
    assert "latitude" not in blob
    assert "longitude" not in blob


def test_road_network_context_unavailable_when_catalog_empty(monkeypatch):
    monkeypatch.setattr(operational.road_catalog, "list_road_catalog", lambda session, ctx: ([], {}))

    evidence = operational.road_network_context(object(), _context())

    assert evidence.available is False
    assert evidence.value is None
    assert evidence.status == EvidenceStatus.UNAVAILABLE
    assert evidence.kind == EvidenceKind.FACT


def test_registry_dispatches_road_network_context(monkeypatch):
    captured = {}

    def fake_context(session, ctx, *, equipment_id=None, zone_id=None, parameters=None):
        captured["parameters"] = parameters
        return EvidenceItem(
            kind=EvidenceKind.FACT,
            source_tool="road_network_context",
            source_service="app.services.operational.road_network.build_route_context",
            metric="road_network_context",
            value={"reachable": True, "candidatePaths": []},
        )

    monkeypatch.setattr(operational, "road_network_context", fake_context)
    request = EvidenceRequest(
        request_type=EvidenceRequestType.ROAD_NETWORK_CONTEXT,
        parameters=["BANC_A", "CRUSHER"],
        reason="Need haul-road alternatives after the primary route closed.",
    )

    evidence = EvidenceToolRegistry(object()).dispatch(_context(), request)

    assert captured["parameters"] == ["BANC_A", "CRUSHER"]
    assert evidence.source_tool == "road_network_context"
    assert evidence.metadata["requestId"] == request.request_id


def test_congestion_initial_evidence_includes_road_network_context(monkeypatch):
    captured = []

    def fake_safe(self, ctx, name, call, **kwargs):
        captured.append(name)
        return EvidenceItem(
            kind=EvidenceKind.FACT,
            source_tool=name,
            source_service="test",
            metric=name,
            value={},
        )

    monkeypatch.setattr(EvidenceToolRegistry, "_safe_call", fake_safe)
    trigger = InvestigationTrigger(
        trigger_type=TriggerType.CONGESTION_RISK,
        trigger_source=TriggerSource.AUTOMATIC_MONITORING,
        site_id=1,
        shift_id=2,
        zone_id=4,
        occurred_at=_context().sim_now,
        payload={"reason": "queue inflation on haul to crusher"},
    )

    EvidenceToolRegistry(object()).gather_initial(_context(), trigger)

    assert "road_network_context" in captured


def test_mechanical_anomaly_does_not_auto_include_road_network(monkeypatch):
    captured = []

    def fake_safe(self, ctx, name, call, **kwargs):
        captured.append(name)
        return EvidenceItem(
            kind=EvidenceKind.FACT,
            source_tool=name,
            source_service="test",
            metric=name,
            value={},
        )

    monkeypatch.setattr(EvidenceToolRegistry, "_safe_call", fake_safe)
    trigger = InvestigationTrigger(
        trigger_type=TriggerType.EQUIPMENT_ANOMALY,
        trigger_source=TriggerSource.EXISTING_ALERT,
        site_id=1,
        equipment_id=7,
        occurred_at=_context().sim_now,
        payload={"title": "Engine oil pressure low"},
    )

    EvidenceToolRegistry(object()).gather_initial(_context(), trigger)

    assert "road_network_context" not in captured

