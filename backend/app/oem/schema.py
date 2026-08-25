"""Ensure OEM tables exist (no Alembic)."""

from sqlalchemy import text
from sqlalchemy.orm import Session

def ensure_oem_schema(session: Session) -> None:
    session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS tyre_telemetry (
              tyre_telemetry_id BIGSERIAL PRIMARY KEY,
              equipment_id BIGINT NOT NULL REFERENCES equipment(equipment_id) ON DELETE CASCADE,
              ts TIMESTAMPTZ NOT NULL,
              position VARCHAR(12) NOT NULL,
              pressure_kpa NUMERIC(10,2),
              temperature_c NUMERIC(8,2),
              UNIQUE(equipment_id, ts, position)
            )
            """
        )
    )
    session.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_tyre_telemetry_equipment_ts
              ON tyre_telemetry(equipment_id, ts DESC)
            """
        )
    )
    session.commit()
