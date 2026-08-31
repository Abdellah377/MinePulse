from datetime import datetime, timedelta, timezone

from app.db.enums import AlertSeverity, AlertSource, AlertStatus
from app.db.models import Alert
from app.services.operational.alerts import (
    count_active_alerts,
    decode_alert_cursor,
    encode_alert_cursor,
    paginate_alert_rows,
)


def _alert(pk: int, *, minutes: int, status: AlertStatus = AlertStatus.NEW) -> Alert:
    occurred = datetime(2026, 8, 31, 10, 0, tzinfo=timezone.utc) - timedelta(minutes=minutes)
    return Alert(
        alert_id=pk,
        created_at=occurred,
        occurred_at=occurred,
        source=AlertSource.RULE,
        severity=AlertSeverity.WARNING,
        status=status,
        alert_type="CONGESTION_RISK",
        title=f"a-{pk}",
        metadata_={},
    )


def test_cursor_roundtrip_and_page_does_not_include_newer_arrivals():
    first = encode_alert_cursor(datetime(2026, 8, 31, 12, tzinfo=timezone.utc), 10)
    when, pk = decode_alert_cursor(first)
    assert pk == 10
    assert when.year == 2026
    rows = [_alert(i, minutes=i) for i in range(1, 8)]
    page1 = paginate_alert_rows(rows, limit=3)
    assert [row.alert_id for row in page1["items"]] == [1, 2, 3]
    assert page1["hasMore"] is True
    page2 = paginate_alert_rows(rows, limit=3, cursor=page1["nextCursor"])
    assert [row.alert_id for row in page2["items"]] == [4, 5, 6]
    newer = _alert(99, minutes=-5)
    still = paginate_alert_rows(rows + [newer], limit=3, cursor=page1["nextCursor"])
    assert 99 not in [row.alert_id for row in still["items"]]


def test_active_only_excludes_resolved_and_keeps_history_rows():
    rows = [
        _alert(1, minutes=1),
        _alert(2, minutes=2, status=AlertStatus.RESOLVED),
        _alert(3, minutes=3),
    ]
    active = paginate_alert_rows(rows, limit=20, active_only=True)
    assert [row.alert_id for row in active["items"]] == [1, 3]
    history = paginate_alert_rows(rows, limit=20, active_only=False)
    assert [row.alert_id for row in history["items"]] == [1, 2, 3]


def test_count_active_alerts_uses_sql_filter(monkeypatch):
    class ScalarSession:
        def scalar(self, _query):
            return 4

    assert count_active_alerts(ScalarSession(), 17) == 4
