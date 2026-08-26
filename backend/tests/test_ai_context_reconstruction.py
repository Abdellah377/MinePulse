from datetime import datetime, timezone
import pytest
from fastapi import HTTPException

from app.ai.contracts import InvestigationTrigger, ResolvedOperationalContext
from app.ai.service import reconstruct_operational_context, validate_trigger_scope
from app.db.models import Shift, Site


class FakeSession:
    def __init__(self, site, shift):
        self.site = site
        self.shift = shift

    def get(self, model, key):
        if model is Site and key == self.site.site_id:
            return self.site
        if model is Shift and self.shift is not None and key == self.shift.shift_id:
            return self.shift
        return None


def test_context_reconstructs_from_serializable_ids_and_recorded_window():
    site = Site(site_id=1, code="SITE-A", name="Site A", active=True)
    shift = Shift(shift_id=2, site_id=1, name="Day")
    serialized = ResolvedOperationalContext(
        site_id=1,
        site_code="SITE-A",
        site_name="Site A",
        shift_id=2,
        shift_name="Day",
        operational_now=datetime(2026, 8, 25, 10, tzinfo=timezone.utc),
        window_start=datetime(2026, 8, 25, 6, tzinfo=timezone.utc),
        window_end=datetime(2026, 8, 25, 14, tzinfo=timezone.utc),
    )

    reconstructed = reconstruct_operational_context(FakeSession(site, shift), serialized)

    assert reconstructed.site is site
    assert reconstructed.shift is shift
    assert reconstructed.sim_now == serialized.operational_now
    assert reconstructed.shift_window_start == serialized.window_start
    assert reconstructed.shift_window_end == serialized.window_end


@pytest.mark.parametrize("shift", [None, Shift(shift_id=2, site_id=99, name="Other site")])
def test_invalid_shift_is_rejected_before_creating_unpersistable_investigation(shift):
    site = Site(site_id=1, code="SITE-A", name="Site A", active=True)
    trigger = InvestigationTrigger(site_id=1, shift_id=2, trigger_type="PRODUCTION_DEVIATION", trigger_source="USER_INVESTIGATE")
    with pytest.raises(HTTPException) as caught:
        validate_trigger_scope(FakeSession(site, shift), trigger)
    assert caught.value.status_code == 404
