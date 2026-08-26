from datetime import datetime, timezone

from app.ai.contracts import (
    InvestigationStatus,
    InvestigationTrigger,
    ResolvedOperationalContext,
    TriggerSource,
    TriggerType,
)
from app.ai.graph import initial_state
from app.ai.persistence import persist_investigation, record_to_result


class FakeSession:
    def __init__(self):
        self.row = None

    def get(self, model, key):
        return self.row

    def add(self, row):
        self.row = row

    def commit(self):
        return None

    def refresh(self, row):
        return None


def test_trigger_type_and_source_persist_as_separate_semantics():
    trigger = InvestigationTrigger(
        trigger_type=TriggerType.MAINTENANCE_RISK,
        trigger_source=TriggerSource.EXISTING_ALERT,
        source="maintenance-alerts",
        source_record_id="alert-73",
        site_id=1,
        equipment_id=9,
    )
    state = initial_state(trigger, max_iterations=3, provider="mock", model="mock-model")
    state["operational_context"] = ResolvedOperationalContext(
        site_id=1,
        site_code="SITE-A",
        site_name="Site A",
        shift_id=2,
        shift_name="Day",
        operational_now=datetime(2026, 8, 25, 10, tzinfo=timezone.utc),
        window_start=datetime(2026, 8, 25, 6, tzinfo=timezone.utc),
        window_end=datetime(2026, 8, 25, 14, tzinfo=timezone.utc),
    )
    state["status"] = InvestigationStatus.COMPLETED_WITH_UNCERTAINTY
    state["completed_at"] = datetime(2026, 8, 25, 10, 1, tzinfo=timezone.utc)
    session = FakeSession()

    row = persist_investigation(session, state)
    result = record_to_result(row)

    assert row.trigger_type == "MAINTENANCE_RISK"
    assert row.trigger_source == "EXISTING_ALERT"
    assert row.trigger_data["source"] == "maintenance-alerts"
    assert result.trigger.trigger_type == TriggerType.MAINTENANCE_RISK
    assert result.trigger.trigger_source == TriggerSource.EXISTING_ALERT
