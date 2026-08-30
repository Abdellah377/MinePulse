"""Equipment detail endpoint contract."""

from __future__ import annotations

import pytest


@pytest.mark.skipif(
    "not config.getoption('--integration', default=False)",
    reason="integration tests require --integration and DATABASE_URL",
)
def test_equipment_detail_contract(client):
    live = client.get("/api/equipment/live").json()
    if not live:
        pytest.skip("no equipment in test DB")
    code = live[0]["code"]
    res = client.get(f"/api/equipment/{code}/detail")
    assert res.status_code == 200
    body = res.json()
    assert "equipment" in body
    assert "maintenanceHistory" in body
    assert "failureRisk" in body
    assert body["equipment"]["code"] == code
    assert "predictedFor" not in body["failureRisk"]
