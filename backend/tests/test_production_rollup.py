"""shiftly_attainment: missing target is null, not 0%."""

from app.services.operational.production import shiftly_attainment


def test_null_target_yields_null_metrics():
    out = shiftly_attainment(1000.0, None)
    assert out["attainmentPct"] is None
    assert out["gapTons"] is None
    assert out["gapPct"] is None


def test_zero_target_yields_null_metrics():
    out = shiftly_attainment(1000.0, 0.0)
    assert out["attainmentPct"] is None


def test_real_target_computes_attainment():
    out = shiftly_attainment(38000.0, 42000.0)
    assert out["attainmentPct"] == 90.5
    assert out["gapTons"] == 4000.0
