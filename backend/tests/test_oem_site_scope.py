from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy.dialects import postgresql

from app.db.models import Equipment
from app.oem.queries import error_codes, get_equipment_signal_history


class _ScalarResult:
    def __init__(self, rows=None):
        self._rows = rows or []

    def all(self):
        return self._rows


class _DuplicateCodeSession:
    def __init__(self):
        self.statements = []

    def scalar(self, statement):
        sql = _sql(statement)
        self.statements.append(sql)
        if "equipment.code = 'TR-01'" in sql and "equipment.site_id = 2" not in sql:
            return SimpleNamespace(equipment_id=1, site_id=1, code="TR-01")
        return None

    def scalars(self, statement):
        self.statements.append(_sql(statement))
        return _ScalarResult()


class _EventSession:
    def __init__(self):
        self.statements = []

    def scalars(self, statement):
        self.statements.append(_sql(statement))
        return _ScalarResult()


def _sql(statement) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def test_oem_telemetry_does_not_resolve_duplicate_code_globally():
    session = _DuplicateCodeSession()
    ctx = SimpleNamespace(
        shift_window_start=datetime(2026, 8, 21, 6, 0, tzinfo=timezone.utc),
        sim_now=datetime(2026, 8, 21, 10, 0, tzinfo=timezone.utc),
    )

    data = get_equipment_signal_history(
        session,
        "TR-01",
        None,
        None,
        ["speed_kmh"],
        site_id=2,
        ctx=ctx,
    )

    assert data == {"error": "not_found"}
    assert "equipment.site_id = 2" in session.statements[0]


def test_equipment_code_is_unique_only_within_site_in_orm():
    assert Equipment.__table__.c.code.unique is not True
    unique_columns = {
        tuple(col.name for col in constraint.columns)
        for constraint in Equipment.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("site_id", "code") in unique_columns


def test_oem_error_query_filters_events_to_current_site():
    session = _EventSession()
    ctx = SimpleNamespace(
        shift_window_start=datetime(2026, 8, 21, 6, 0, tzinfo=timezone.utc),
        sim_now=datetime(2026, 8, 21, 10, 0, tzinfo=timezone.utc),
    )

    assert error_codes(session, None, None, None, None, None, None, None, site_id=2, ctx=ctx) == []

    assert "equipment.site_id = 2" in session.statements[0]
