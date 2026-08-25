"""Bootstrap lite mode must not corrupt productionByShift shape."""

from __future__ import annotations

import pytest


@pytest.mark.skipif(
    "not config.getoption('--integration', default=False)",
    reason="integration tests require --integration and DATABASE_URL",
)
def test_bootstrap_lite_omits_production(client):
    full = client.get("/api/bootstrap").json()
    lite = client.get("/api/bootstrap?lite=true").json()
    assert "productionByShift" in full
    assert "productionByShift" not in lite
    assert isinstance(full["productionByShift"]["hourly"], list)
    assert isinstance(full["productionByShift"]["shiftly"], list)


def test_bootstrap_lite_omits_production_unit():
    """Unit-level contract without DB."""
    lite_keys = {"sites", "shifts", "zones", "equipment", "simNow"}
    assert "productionByShift" not in lite_keys
