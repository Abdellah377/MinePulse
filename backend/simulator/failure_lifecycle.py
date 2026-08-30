"""Persistence lifecycle for observable mechanical incidents."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.enums import AlertSeverity
from app.db.models import DowntimeEvent, Equipment, MaintenanceEvent


@dataclass(frozen=True)
class PersistedFailureRecords:
    maintenance_id: int
    downtime_id: int

    def maintenance(self, session: Session) -> MaintenanceEvent:
        row = session.get(MaintenanceEvent, self.maintenance_id)
        if row is None:
            raise RuntimeError("mechanical incident maintenance record is missing")
        return row

    def downtime(self, session: Session) -> DowntimeEvent:
        row = session.get(DowntimeEvent, self.downtime_id)
        if row is None:
            raise RuntimeError("mechanical incident downtime record is missing")
        return row


def start_mechanical_incident(
    session: Session,
    *,
    equipment_id: int,
    started_at: datetime,
    expected_recovery_at: datetime,
    severity: AlertSeverity,
) -> PersistedFailureRecords:
    """Persist only operationally observable failure records.

    The detailed component/cause remains unknown.  Hidden simulator profile
    names, seeds, progress and run identifiers are intentionally absent.
    """

    maintenance = MaintenanceEvent(
        equipment_id=equipment_id,
        type="UNPLANNED_STOP",
        component=None,
        description="Unexpected mechanical stop pending inspection and diagnosis.",
        start_time=started_at,
        expected_end_time=expected_recovery_at,
        severity=severity,
        status="OPEN",
        planned=False,
        metadata_={"source": "SIMULATOR_FAILURE"},
    )
    downtime = DowntimeEvent(
        equipment_id=equipment_id,
        start_time=started_at,
        category="MECHANICAL",
        reason="Unexpected mechanical stop; detailed cause pending diagnosis.",
        source="SIMULATOR",
        confirmed=True,
    )
    session.add_all([maintenance, downtime])
    session.flush()
    return PersistedFailureRecords(
        maintenance_id=maintenance.maintenance_id,
        downtime_id=downtime.downtime_id,
    )


def recover_mechanical_incident(
    session: Session,
    records: PersistedFailureRecords,
    *,
    recovered_at: datetime,
) -> None:
    maintenance = records.maintenance(session)
    downtime = records.downtime(session)
    maintenance.actual_end_time = _safe_end(maintenance.start_time, recovered_at)
    maintenance.status = "CLOSED"
    downtime.end_time = _safe_end(downtime.start_time, recovered_at)


def reconcile_open_simulation_failures(
    session: Session,
    *,
    site_id: int,
    reconciled_at: datetime,
) -> dict[str, int]:
    """Close simulator-site failure records that cannot resume after restart."""

    equipment_ids = select(Equipment.equipment_id).where(Equipment.site_id == site_id)
    maintenance_rows = list(
        session.scalars(
            select(MaintenanceEvent).where(
                MaintenanceEvent.equipment_id.in_(equipment_ids),
                MaintenanceEvent.status == "OPEN",
                MaintenanceEvent.type == "UNPLANNED_STOP",
                MaintenanceEvent.metadata_["source"].astext == "SIMULATOR_FAILURE",
            )
        ).all()
    )
    downtime_rows = list(
        session.scalars(
            select(DowntimeEvent).where(
                DowntimeEvent.equipment_id.in_(equipment_ids),
                DowntimeEvent.end_time.is_(None),
                DowntimeEvent.category == "MECHANICAL",
                DowntimeEvent.source == "SIMULATOR",
            )
        ).all()
    )
    for row in maintenance_rows:
        row.actual_end_time = _safe_end(row.start_time, reconciled_at)
        row.status = "CLOSED"
    for row in downtime_rows:
        row.end_time = _safe_end(row.start_time, reconciled_at)
    session.flush()
    return {"maintenance_events": len(maintenance_rows), "downtime_events": len(downtime_rows)}


def _safe_end(started_at: datetime, ended_at: datetime) -> datetime:
    """Compare DB-returned naive values and aware operational timestamps safely."""

    start = started_at if started_at.tzinfo else started_at.replace(tzinfo=timezone.utc)
    end = ended_at if ended_at.tzinfo else ended_at.replace(tzinfo=timezone.utc)
    return max(start, end)
