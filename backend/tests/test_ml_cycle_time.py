"""Zero-cost tests for cycle-time V1. No LLM, no live database required."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from inspect import signature
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.ml.cycle_time.baselines import MedianBaselines
from app.ml.cycle_time.contracts import (
    DETERMINISTIC_SERVED_PREDICTOR,
    MIN_ML_RELATIVE_MAE_IMPROVEMENT,
    MODEL_VERSION,
    CycleTimeStatus,
    ModelStatus,
    TRAINING_DATA_TYPE,
)
from app.ml.cycle_time.dataset import (
    CycleRecord,
    CycleSnapshot,
    EquipmentInfo,
    StateInterval,
    is_valid_training_cycle,
    load_snapshot,
    select_training_cycles,
    training_target_minutes,
)
from app.ml.cycle_time.evaluation import apply_residual_bounds, residual_quantiles, targets
from app.ml.cycle_time.features import (
    FEATURE_NAMES,
    FORBIDDEN_FEATURE_NAMES,
    assert_no_forbidden_features,
    build_feature_rows,
)
from app.ml.cycle_time.inference import predict_cycle_time, predict_feature_rows, predict_from_snapshot, resolve_artifact
from app.ml.cycle_time.model import build_pipeline, predict_pipeline, rows_to_matrix
from app.ml.cycle_time.policy import ServingDecision, select_served_predictor
from app.ml.cycle_time.train import temporal_split, train_from_rows

T0 = datetime(2026, 1, 29, 7, 0, tzinfo=timezone.utc)


def _at(minutes: int) -> datetime:
    return T0 + timedelta(minutes=minutes)


def _cycle(
    cycle_id: int,
    *,
    truck_id: int = 1,
    loader_id: int | None = 100,
    origin: int | None = 10,
    dest: int | None = 20,
    start: int = 0,
    duration_min: int = 100,
    status: str = "COMPLETED",
    duration_sec: int | None = None,
    completed_at: datetime | None = None,
    started_at: datetime | None = None,
) -> CycleRecord:
    started = started_at if started_at is not None else _at(start)
    completed = completed_at
    if status == "COMPLETED" and completed is None and started is not None:
        completed = started + timedelta(minutes=duration_min)
    sec = duration_sec
    if status == "COMPLETED" and sec is None:
        sec = duration_min * 60
    return CycleRecord(
        cycle_id=cycle_id,
        truck_id=truck_id,
        loader_id=loader_id,
        origin_zone_id=origin,
        destination_zone_id=dest,
        started_at=started,
        completed_at=completed,
        total_duration_sec=sec,
        status=status,
        payload_t=180.0 if status == "COMPLETED" else None,
        distance_km=4.2 if status == "COMPLETED" else None,
    )


def _catalog() -> tuple[dict[int, EquipmentInfo], dict[int, str], dict[tuple[int, int], float]]:
    equipment = {
        1: EquipmentInfo(1, "TRK-001", "CAT 793F", 220.0),
        2: EquipmentInfo(2, "TRK-002", "CAT 793F", 220.0),
        3: EquipmentInfo(3, "TRK-003", "Komatsu", 180.0),
        4: EquipmentInfo(4, "TRK-004", "CAT 793F", 220.0),
        100: EquipmentInfo(100, "EXC-001", "EX5600", None),
        101: EquipmentInfo(101, "EXC-002", "EX5600", None),
    }
    zones = {10: "BANC_A", 11: "BANC_B", 20: "DUMP_S", 21: "CRUSHER"}
    roads = {(10, 20): 4.2, (11, 20): 5.1, (10, 21): 3.8, (11, 21): 6.0}
    return equipment, zones, roads


def _snapshot(cycles: list[CycleRecord], waiting: list[StateInterval] | None = None) -> CycleSnapshot:
    equipment, zones, roads = _catalog()
    return CycleSnapshot(
        cycles=cycles,
        equipment=equipment,
        zones=zones,
        road_distance_km=roads,
        waiting_states=waiting or [],
    )


def test_active_and_invalid_targets_excluded():
    cycles = [
        _cycle(1, status="ACTIVE", duration_sec=None, completed_at=None),
        _cycle(2, duration_min=100),  # placeholder, replaced below
        _cycle(3, duration_sec=0),
        _cycle(4, duration_sec=-10),
        _cycle(5, duration_min=90, duration_sec=6000),
        _cycle(6, truck_id=None, duration_min=90),  # type: ignore[arg-type]
        _cycle(7, duration_min=90),
    ]
    cycles[1] = CycleRecord(
        cycle_id=2, truck_id=1, loader_id=100, origin_zone_id=10, destination_zone_id=20,
        started_at=_at(0), completed_at=_at(100), total_duration_sec=None, status="COMPLETED",
    )
    kept, excluded = select_training_cycles(cycles)
    assert [row.cycle_id for row in kept] == [7]
    assert excluded["not_completed"] == 1
    assert excluded["missing_target"] == 1
    assert excluded["non_positive_duration"] == 2
    assert excluded["duration_mismatch"] == 1
    assert excluded["missing_truck_id"] == 1
    assert training_target_minutes(kept[0]) == 90.0


def test_null_target_is_not_zero():
    active = _cycle(1, status="ACTIVE", duration_sec=None, completed_at=None)
    ok, reason = is_valid_training_cycle(active)
    assert ok is False
    assert training_target_minutes(active) is None


def test_target_matches_authoritative_duration():
    row = _cycle(1, duration_min=108)
    assert row.total_duration_sec == 6480
    assert training_target_minutes(row) == 108.0
    assert (row.completed_at - row.started_at).total_seconds() == 6480


def test_forbidden_names_are_not_features():
    assert FORBIDDEN_FEATURE_NAMES.isdisjoint(FEATURE_NAMES)
    assert "completed_at" not in FEATURE_NAMES
    assert "total_duration_sec" not in FEATURE_NAMES
    assert "payload_t" not in FEATURE_NAMES
    assert "distance_km" not in FEATURE_NAMES
    assert "shift_id" not in FEATURE_NAMES
    assert "performance_factor" not in FEATURE_NAMES
    try:
        assert_no_forbidden_features(["truck_code", "completed_at"])
        raise AssertionError("expected forbidden feature error")
    except ValueError as exc:
        assert "completed_at" in str(exc)


def test_historical_median_uses_only_prior_completions():
    cycles = [
        _cycle(1, truck_id=1, start=0, duration_min=120),
        _cycle(2, truck_id=1, start=60, duration_min=90),
        _cycle(3, truck_id=1, start=130, duration_min=100),
    ]
    rows = build_feature_rows(cycles, _snapshot(cycles))
    by_id = {row.cycle_id: row for row in rows}
    assert by_id[2].values["truck_prior_median"] is None
    assert by_id[3].values["truck_prior_median"] == 120.0
    assert "payload_t" not in by_id[3].values
    assert "distance_km" not in by_id[3].values


def test_later_cycle_cannot_leak_into_earlier_history():
    early = _cycle(1, truck_id=1, start=0, duration_min=80)
    late = _cycle(2, truck_id=1, start=200, duration_min=200)
    rows = build_feature_rows([early], _snapshot([early, late]))
    assert rows[0].values["truck_prior_median"] is None


def test_queue_is_point_in_time_not_future_wait():
    current = _cycle(10, truck_id=1, loader_id=100, start=60, duration_min=100)
    other_open = _cycle(11, truck_id=2, loader_id=100, start=50, duration_min=80)
    future_wait = StateInterval(2, "WAITING_LOADING", _at(90), _at(110))
    present_wait = StateInterval(2, "WAITING_LOADING", _at(50), _at(70))
    with_present = build_feature_rows([current], _snapshot([current, other_open], [present_wait]))
    with_future = build_feature_rows([current], _snapshot([current, other_open], [future_wait]))
    assert with_present[0].values["loader_waiting_truck_count"] == 1.0
    assert with_future[0].values["loader_waiting_truck_count"] == 0.0
    null_loader = build_feature_rows(
        [_cycle(12, truck_id=1, loader_id=None, start=60, duration_min=100)],
        _snapshot([_cycle(12, truck_id=1, loader_id=None, start=60, duration_min=100)]),
    )
    assert null_loader[0].values["loader_waiting_truck_count"] is None


def test_catalog_distance_not_cycle_distance():
    row = _cycle(1, origin=11, dest=20, duration_min=100)
    features = build_feature_rows([row], _snapshot([row]))[0]
    assert features.values["catalog_distance_km"] == 5.1
    assert row.distance_km == 4.2


def test_temporal_split_has_no_overlap_and_is_ordered():
    cycles = [_cycle(i, truck_id=1 + (i % 4), start=i * 20, duration_min=90 + (i % 5) * 4) for i in range(1, 31)]
    rows = build_feature_rows(cycles, _snapshot(cycles))
    train, val, test = temporal_split(rows)
    ids = [row.cycle_id for row in train] + [row.cycle_id for row in val] + [row.cycle_id for row in test]
    assert len(ids) == len(set(ids)) == 30
    assert train[-1].started_at <= val[0].started_at <= test[0].started_at
    assert train[0].started_at < test[-1].started_at


def test_baseline_unseen_category_falls_back_to_global():
    cycles = [_cycle(i, truck_id=1, origin=10, dest=20, start=i * 30, duration_min=100 + i) for i in range(1, 9)]
    rows = build_feature_rows(cycles, _snapshot(cycles))
    fitted = MedianBaselines().fit(rows)
    unseen = build_feature_rows([_cycle(99, truck_id=3, origin=11, dest=21, start=400, duration_min=130)], _snapshot(cycles + [_cycle(99, truck_id=3, origin=11, dest=21, start=400, duration_min=130)]))
    assert fitted.predict_truck(unseen) == [fitted.global_median]
    assert fitted.predict_route(unseen) == [fitted.global_median]
    assert fitted.predict_truck_route_global(unseen) == [fitted.global_median]
    assert fitted.predict_truck_route_global(unseen)[0] != 0


def test_hierarchical_fallback_truck_then_route_then_global():
    cycles = [
        *[_cycle(i, truck_id=1, origin=10, dest=20, start=i * 30, duration_min=80) for i in range(1, 6)],
        *[_cycle(i, truck_id=2, origin=11, dest=21, start=200 + i * 30, duration_min=140) for i in range(6, 11)],
    ]
    rows = build_feature_rows(cycles, _snapshot(cycles))
    fitted = MedianBaselines().fit(rows)
    assert fitted.global_median != 0

    known_truck = build_feature_rows(
        [_cycle(90, truck_id=1, origin=11, dest=21, start=500, duration_min=130)],
        _snapshot(cycles + [_cycle(90, truck_id=1, origin=11, dest=21, start=500, duration_min=130)]),
    )
    assert fitted.predict_truck_route_global(known_truck) == [fitted.by_truck["TRK-001"]]

    unseen_truck_known_route = build_feature_rows(
        [_cycle(91, truck_id=3, origin=10, dest=20, start=510, duration_min=130)],
        _snapshot(cycles + [_cycle(91, truck_id=3, origin=10, dest=20, start=510, duration_min=130)]),
    )
    route_median = fitted.by_route["BANC_A|DUMP_S"]
    assert fitted.predict_truck_route_global(unseen_truck_known_route) == [route_median]
    assert route_median != fitted.global_median

    unseen_both = build_feature_rows(
        [_cycle(92, truck_id=3, origin=11, dest=20, start=520, duration_min=130)],
        _snapshot(cycles + [_cycle(92, truck_id=3, origin=11, dest=20, start=520, duration_min=130)]),
    )
    assert fitted.predict_truck_route_global(unseen_both) == [fitted.global_median]
    assert fitted.predict_truck_route_global(unseen_both)[0] != 0


def test_pipeline_trains_and_returns_finite_predictions():
    cycles = [_cycle(i, truck_id=1 + (i % 4), origin=10 + (i % 2), dest=20, start=i * 25, duration_min=90 + (i % 7) * 3) for i in range(1, 25)]
    rows = build_feature_rows(cycles, _snapshot(cycles))
    pipeline = build_pipeline(max_depth=3, min_samples_leaf=5, max_iter=40)
    pipeline.fit(rows_to_matrix(rows), [row.target_minutes for row in rows])
    preds = predict_pipeline(pipeline, rows)
    assert len(preds) == len(rows)
    assert all(pred == pred and pred > 0 for pred in preds)
    assert list(FEATURE_NAMES) == list(FEATURE_NAMES)


def test_residual_bounds_and_train_metadata():
    cycles = [
        _cycle(i, truck_id=1 + (i % 4), loader_id=100 + (i % 2), origin=10 + (i % 2), dest=20, start=i * 20, duration_min=90 + (i % 6) * 5)
        for i in range(1, 41)
    ]
    rows = build_feature_rows(cycles, _snapshot(cycles))
    artifact, report = train_from_rows(rows, excluded={"not_completed": 2})
    assert report["training_data_type"] == TRAINING_DATA_TYPE
    assert report["model_version"] == MODEL_VERSION
    assert "synthetic" in report["synthetic_data_warning"].lower()
    assert report["feature_schema"] == list(FEATURE_NAMES)
    assert report["split"]["train"]["n"] + report["split"]["validation"]["n"] + report["split"]["test"]["n"] == 40
    lo, pred, hi = artifact.residual_q10, 100.0, artifact.residual_q90
    bounded = apply_residual_bounds(pred, artifact.residual_q10, artifact.residual_q90)
    assert bounded[1] <= bounded[0] <= bounded[2]
    val_pred = predict_feature_rows(artifact, rows[-6:])
    for value, lower, upper in val_pred:
        assert lower <= value <= upper
        assert math_isfinite(value)
    expected = select_served_predictor(
        report["hgb_validation"]["mae"],
        {name: metrics["mae"] for name, metrics in report["baseline_validation"].items()},
    )
    assert report["promotion_threshold"] == MIN_ML_RELATIVE_MAE_IMPROVEMENT
    assert report["selection"]["test_set_used_for_selection"] is False
    assert report["served_predictor"] == expected.served_predictor
    assert report["ml_promoted"] == expected.ml_promoted
    assert report["decision_reason"] == expected.decision_reason
    assert report["hgb_validation_mae"] == report["hgb_validation"]["mae"]
    assert report["best_baseline_validation_mae"] == expected.best_baseline_mae
    assert "truck_route_global" in report["baseline_validation"]
    assert artifact.pipeline is not None
    assert artifact.served_predictor == report["served_predictor"]
    if report["ml_promoted"]:
        assert report["model_status"] == ModelStatus.MODEL_BEATS_BASELINE.value
        assert report["served_predictor"] == "hgb"
        assert report["relative_mae_improvement"] >= MIN_ML_RELATIVE_MAE_IMPROVEMENT
    else:
        assert report["model_status"] == ModelStatus.BASELINE_NOT_BEATEN.value
        assert report["served_predictor"] == DETERMINISTIC_SERVED_PREDICTOR
        assert report["hgb_role"] == "experimental"

    train, val, _test = temporal_split(rows)
    if artifact.served_predictor == "hgb":
        served_preds = predict_pipeline(artifact.pipeline, val)
    else:
        served_preds = artifact.baselines.predict(artifact.served_predictor, val)
    q10, q90 = residual_quantiles(targets(val), served_preds)
    assert artifact.residual_q10 == q10
    assert artifact.residual_q90 == q90
    _ = lo, hi


def math_isfinite(value: float) -> bool:
    return value == value and abs(value) != float("inf")


def test_inference_available_unavailable_and_insufficient_history(tmp_path: Path):
    missing = resolve_artifact(artifacts_dir=tmp_path)
    assert missing.status == CycleTimeStatus.UNAVAILABLE.value or missing.status == CycleTimeStatus.UNAVAILABLE

    cycles = [
        _cycle(i, truck_id=1 + (i % 3), origin=10, dest=20, start=i * 22, duration_min=95 + (i % 4) * 4)
        for i in range(1, 36)
    ]
    snapshot = _snapshot(cycles)
    rows = build_feature_rows(cycles, snapshot)
    artifact, report = train_from_rows(rows)
    assert report["model_version"] == MODEL_VERSION

    result = predict_from_snapshot(snapshot, 20, artifact)
    assert result.status == CycleTimeStatus.AVAILABLE.value or result.status == CycleTimeStatus.AVAILABLE
    assert result.predicted_minutes is not None
    assert result.lower_bound_minutes <= result.predicted_minutes <= result.upper_bound_minutes
    assert result.data_class == "synthetic_prototype"
    assert result.model_version == MODEL_VERSION
    assert result.feature_timestamp == result.prediction_timestamp

    broken = _cycle(500, start=0, duration_min=90)
    broken = CycleRecord(
        cycle_id=500, truck_id=None, loader_id=100, origin_zone_id=10, destination_zone_id=20,
        started_at=_at(0), completed_at=_at(90), total_duration_sec=5400, status="COMPLETED",
    )
    insufficient = predict_from_snapshot(_snapshot(cycles + [broken]), 500, artifact)
    assert insufficient.status == CycleTimeStatus.INSUFFICIENT_HISTORY.value or insufficient.status == CycleTimeStatus.INSUFFICIENT_HISTORY

    mismatch = artifact
    mismatch.feature_names = ("not_a_real_feature",)
    bad_schema = resolve_artifact(artifact=mismatch)
    assert bad_schema.status == CycleTimeStatus.UNAVAILABLE.value or bad_schema.status == CycleTimeStatus.UNAVAILABLE


class _Rows:
    def __init__(self, values):
        self._values = values

    def all(self):
        return self._values


class _CycleSnapshotSession:
    def __init__(self, site_id, rows_by_entity):
        self.site_id = site_id
        self.rows_by_entity = rows_by_entity

    def scalars(self, statement):
        sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
        assert f"site_id = {self.site_id}" in sql
        entity = statement.column_descriptions[0]["entity"]
        return _Rows(self.rows_by_entity[entity])


def test_cycle_snapshot_loader_scopes_cycles_catalog_and_waiting_states_to_requested_site():
    from app.db.models import Cycle, Equipment, HaulRoad, Zone
    from app.db.models.telemetry import EquipmentState as EquipmentStateRow

    session = _CycleSnapshotSession(
        7,
        {
            Cycle: [
                SimpleNamespace(
                    cycle_id=10,
                    truck_id=1,
                    loader_id=None,
                    origin_zone_id=20,
                    destination_zone_id=21,
                    started_at=_at(0),
                    completed_at=None,
                    total_duration_sec=None,
                    status="ACTIVE",
                    payload_t=None,
                    distance_km=None,
                )
            ],
            Equipment: [SimpleNamespace(equipment_id=1, code="TRK-S7", model=None, capacity_t=None)],
            Zone: [
                SimpleNamespace(zone_id=20, code="PIT-S7"),
                SimpleNamespace(zone_id=21, code="DUMP-S7"),
            ],
            HaulRoad: [SimpleNamespace(from_zone_id=20, to_zone_id=21, distance_km=4.2)],
            EquipmentStateRow: [
                SimpleNamespace(equipment_id=1, state="WAITING_LOADING", start_time=_at(0), end_time=None)
            ],
        },
    )

    snapshot = load_snapshot(session, site_id=7)

    assert [cycle.cycle_id for cycle in snapshot.cycles] == [10]
    assert set(snapshot.equipment) == {1}
    assert set(snapshot.zones) == {20, 21}
    assert snapshot.road_distance_km == {(20, 21): 4.2}
    assert [state.equipment_id for state in snapshot.waiting_states] == [1]


def test_cycle_inference_loads_the_requested_site_only(monkeypatch):
    requested_sites = []
    monkeypatch.setattr(
        "app.ml.cycle_time.inference.resolve_artifact",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        "app.ml.cycle_time.inference.load_snapshot",
        lambda _session, *, site_id: requested_sites.append(site_id) or object(),
    )
    monkeypatch.setattr(
        "app.ml.cycle_time.inference.predict_from_snapshot",
        lambda _snapshot, _cycle_id, _artifact: "scoped prediction",
    )

    result = predict_cycle_time(object(), 10, artifact=object(), site_id=7)

    assert result == "scoped prediction"
    assert requested_sites == [7]


def _deterministic_maes() -> dict[str, float]:
    return {"global": 12.0, "route": 11.0, "truck": 10.0, "truck_route_global": 10.0}


def test_hgb_loss_keeps_deterministic_served():
    decision = select_served_predictor(11.0, _deterministic_maes())
    assert decision.ml_promoted is False
    assert decision.served_predictor == DETERMINISTIC_SERVED_PREDICTOR
    assert decision.model_status == ModelStatus.BASELINE_NOT_BEATEN
    assert decision.hgb_role == "experimental"
    assert decision.promotion_threshold == MIN_ML_RELATIVE_MAE_IMPROVEMENT
    meta = decision.metadata()
    assert meta["ml_promoted"] is False
    assert meta["served_predictor"] == "truck_route_global"
    assert "did not beat" in decision.decision_reason


def test_trivial_hgb_win_is_not_promoted():
    for hgb_mae in (9.7, 9.8):
        decision = select_served_predictor(hgb_mae, _deterministic_maes())
        assert decision.ml_promoted is False
        assert decision.served_predictor == DETERMINISTIC_SERVED_PREDICTOR
        assert decision.model_status == ModelStatus.BASELINE_NOT_BEATEN
        assert decision.relative_mae_improvement is not None
        assert decision.relative_mae_improvement < MIN_ML_RELATIVE_MAE_IMPROVEMENT
        assert decision.decision_reason == "ML improvement below minimum promotion threshold"
        assert decision.metadata()["promotion_threshold"] == 0.05


def test_meaningful_hgb_win_is_promoted():
    at_threshold = select_served_predictor(9.5, _deterministic_maes())
    assert at_threshold.ml_promoted is True
    assert at_threshold.served_predictor == "hgb"
    assert at_threshold.model_status == ModelStatus.MODEL_BEATS_BASELINE
    assert at_threshold.relative_mae_improvement >= MIN_ML_RELATIVE_MAE_IMPROVEMENT
    assert at_threshold.hgb_role == "served"
    above = select_served_predictor(9.4, _deterministic_maes())
    assert above.ml_promoted is True
    assert above.served_predictor == "hgb"


def test_select_served_predictor_rejects_test_set_as_an_input():
    params = signature(select_served_predictor).parameters
    assert list(params) == ["hgb_val_mae", "deterministic_val_mae", "threshold"]
    huge_test_win = select_served_predictor(9.7, _deterministic_maes())
    assert huge_test_win.ml_promoted is False
    assert huge_test_win.served_predictor != "hgb"


def test_train_selection_uses_validation_maes_only(monkeypatch):
    captured: dict = {}
    real = select_served_predictor

    def wrapper(hgb_val_mae, deterministic_val_mae, **kwargs):
        captured["hgb"] = hgb_val_mae
        captured["baselines"] = dict(deterministic_val_mae)
        captured["kwargs"] = dict(kwargs)
        return real(hgb_val_mae, deterministic_val_mae, **kwargs)

    monkeypatch.setattr("app.ml.cycle_time.train.select_served_predictor", wrapper)
    cycles = [
        _cycle(i, truck_id=1 + (i % 4), loader_id=100 + (i % 2), origin=10 + (i % 2), dest=20, start=i * 20, duration_min=90 + (i % 6) * 5)
        for i in range(1, 41)
    ]
    rows = build_feature_rows(cycles, _snapshot(cycles))
    artifact, report = train_from_rows(rows)
    assert captured["hgb"] == report["hgb_validation"]["mae"]
    assert set(captured["baselines"]) == set(report["baseline_validation"])
    for name, mae in captured["baselines"].items():
        assert mae == report["baseline_validation"][name]["mae"]
    assert report["selection"]["test_set_used_for_selection"] is False
    expected = real(
        report["hgb_validation"]["mae"],
        {name: metrics["mae"] for name, metrics in report["baseline_validation"].items()},
    )
    assert report["served_predictor"] == expected.served_predictor
    assert report["ml_promoted"] == expected.ml_promoted
    assert artifact.pipeline is not None


def test_runtime_inference_follows_served_predictor():
    cycles = [
        _cycle(i, truck_id=1 + (i % 4), loader_id=100 + (i % 2), origin=10 + (i % 2), dest=20, start=i * 20, duration_min=90 + (i % 6) * 5)
        for i in range(1, 41)
    ]
    rows = build_feature_rows(cycles, _snapshot(cycles))
    artifact, report = train_from_rows(rows)
    sample = rows[-4:]
    hierarchical = artifact.baselines.predict_truck_route_global(sample)
    hgb = predict_pipeline(artifact.pipeline, sample)
    det = replace(artifact, served_predictor="truck_route_global")
    ml = replace(artifact, served_predictor="hgb")
    assert [item[0] for item in predict_feature_rows(det, sample)] == hierarchical
    assert [item[0] for item in predict_feature_rows(ml, sample)] == hgb
    live = [item[0] for item in predict_feature_rows(artifact, sample)]
    if report["served_predictor"] == "hgb":
        assert live == hgb
    else:
        assert live == hierarchical
        assert report["served_predictor"] == DETERMINISTIC_SERVED_PREDICTOR


def test_uncertainty_uses_hgb_residuals_when_hgb_is_served(monkeypatch):
    def always_promote(hgb_val_mae, deterministic_val_mae, **kwargs):
        best = min(deterministic_val_mae, key=deterministic_val_mae.get)
        return ServingDecision(
            served_predictor="hgb",
            model_status=ModelStatus.MODEL_BEATS_BASELINE,
            ml_promoted=True,
            best_baseline=best,
            best_baseline_mae=deterministic_val_mae[best],
            hgb_mae=hgb_val_mae,
            absolute_mae_improvement=1.0,
            relative_mae_improvement=0.10,
            promotion_threshold=MIN_ML_RELATIVE_MAE_IMPROVEMENT,
            decision_reason="forced promotion for test",
            hgb_role="served",
        )

    monkeypatch.setattr("app.ml.cycle_time.train.select_served_predictor", always_promote)
    cycles = [
        _cycle(i, truck_id=1 + (i % 4), loader_id=100 + (i % 2), origin=10 + (i % 2), dest=20, start=i * 20, duration_min=90 + (i % 6) * 5)
        for i in range(1, 41)
    ]
    rows = build_feature_rows(cycles, _snapshot(cycles))
    artifact, report = train_from_rows(rows)
    assert report["served_predictor"] == "hgb"
    assert report["ml_promoted"] is True
    _train, val, _test = temporal_split(rows)
    expected = residual_quantiles(targets(val), predict_pipeline(artifact.pipeline, val))
    assert (artifact.residual_q10, artifact.residual_q90) == expected
    sample = rows[-3:]
    assert [item[0] for item in predict_feature_rows(artifact, sample)] == predict_pipeline(artifact.pipeline, sample)


def test_hgb_artifact_remains_available_when_not_promoted():
    cycles = [
        _cycle(i, truck_id=1 + (i % 4), origin=10 + (i % 2), dest=20, start=i * 22, duration_min=95 + (i % 4) * 4)
        for i in range(1, 36)
    ]
    rows = build_feature_rows(cycles, _snapshot(cycles))
    artifact, report = train_from_rows(rows)
    assert artifact.pipeline is not None
    preds = predict_pipeline(artifact.pipeline, rows[-2:])
    assert len(preds) == 2
    assert all(pred == pred and pred > 0 for pred in preds)
    if not report["ml_promoted"]:
        assert report["hgb_role"] == "experimental"
        assert report["served_predictor"] == DETERMINISTIC_SERVED_PREDICTOR


def test_train_from_database_scopes_snapshot_to_resolved_site(monkeypatch):
    from app.ml.cycle_time import train as train_mod

    requested: list[int] = []
    monkeypatch.setattr(train_mod, "resolve_ml_site_id", lambda _session, site_id=None: site_id or 7)
    monkeypatch.setattr(
        train_mod,
        "load_snapshot",
        lambda _session, *, site_id: requested.append(site_id) or SimpleNamespace(cycles=[]),
    )
    monkeypatch.setattr(train_mod, "select_training_cycles", lambda _cycles: ([], {}))
    monkeypatch.setattr(train_mod, "build_feature_rows", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(train_mod, "train_from_rows", lambda *_args, **_kwargs: (SimpleNamespace(), {"ok": True}))
    monkeypatch.setattr(train_mod, "persist_artifact", lambda *_args, **_kwargs: None)

    report = train_mod.train_from_database(object(), Path("unused-artifacts"), site_id=7)

    assert requested == [7]
    assert report == {"ok": True}
