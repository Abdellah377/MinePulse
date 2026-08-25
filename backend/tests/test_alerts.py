"""Alert status mapping and assignee persistence."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from app.db.enums import AlertSeverity, AlertSource, AlertStatus
from app.db.models import Alert
from app.mappers.dto import alert_to_dto
from app.services.operational.alerts import _UI_STATUS, update_alert


def test_ui_status_mapping():
    assert _UI_STATUS["acknowledged"] == "ACKNOWLEDGED"
    assert _UI_STATUS["resolved"] == "RESOLVED"
    assert _UI_STATUS["assigned"] == "ASSIGNED"
    assert _UI_STATUS["new"] == "NEW"


class _FakeSession:
    def __init__(self, alert: Alert):
        self.alert = alert

    def get(self, model, pk):
        if model is Alert and pk == self.alert.alert_id:
            return self.alert
        return None

    def commit(self):
        return None

    def refresh(self, obj):
        return None


def test_assigned_actor_label_persists_as_assigned_to_label():
    alert = Alert(
        alert_id=42,
        created_at=datetime(2026, 8, 19, tzinfo=timezone.utc),
        source=AlertSource.RULE,
        severity=AlertSeverity.WARNING,
        status=AlertStatus.NEW,
        alert_type="TEST",
        title="unit",
        metadata_={},
    )
    session = _FakeSession(alert)
    out = update_alert(session, "alert-42", status="assigned", actor_label="Régulateur de poste")
    assert out.status == AlertStatus.ASSIGNED
    assert out.metadata_["assigned_to_label"] == "Régulateur de poste"
    assert out.metadata_["last_actor_label"] == "Régulateur de poste"
    dto = alert_to_dto(out, {}, {})
    assert dto["status"] == "assigned"
    assert dto["assignedTo"] == "Régulateur de poste"


def test_alert_patch_assignee_survives_new_session():
    """PATCH-equivalent update_alert → new session GET → same status and assignee. Cleans up."""
    from app.db.database import SessionLocal

    try:
        probe = SessionLocal()
        probe.execute(text("SELECT 1"))
        probe.close()
    except Exception:
        pytest.skip("PostgreSQL not reachable")

    pk: int | None = None
    try:
        s1 = SessionLocal()
        created = Alert(
            created_at=datetime.now(timezone.utc),
            source=AlertSource.RULE,
            severity=AlertSeverity.INFO,
            status=AlertStatus.NEW,
            alert_type="AUDIT_ROUNDTRIP",
            title="pre-ai-alert-roundtrip",
            description="temporary test row — delete after",
            metadata_={},
        )
        s1.add(created)
        s1.commit()
        s1.refresh(created)
        pk = created.alert_id
        s1.close()

        s2 = SessionLocal()
        update_alert(s2, f"alert-{pk}", status="assigned", actor_label="Régulateur de poste")
        s2.close()

        s3 = SessionLocal()
        loaded = s3.get(Alert, pk)
        assert loaded is not None
        dto = alert_to_dto(loaded, {}, {}, session=s3)
        assert dto["status"] == "assigned"
        assert dto["assignedTo"] == "Régulateur de poste"
        s3.close()
    finally:
        if pk is not None:
            cleanup = SessionLocal()
            row = cleanup.get(Alert, pk)
            if row is not None:
                cleanup.delete(row)
                cleanup.commit()
            cleanup.close()
