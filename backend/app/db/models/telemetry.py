from datetime import datetime
from decimal import Decimal

from geoalchemy2 import Geometry
from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.enums import EquipmentState


class EquipmentPosition(Base):
    __tablename__ = "equipment_positions"

    position_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    equipment_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("equipment.equipment_id", ondelete="CASCADE"), nullable=False
    )
    ts: Mapped[datetime] = mapped_column(nullable=False)
    position = mapped_column(Geometry(geometry_type="POINT", srid=4326), nullable=False)
    altitude_m: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    speed_kmh: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    heading_deg: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    gps_accuracy_m: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    zone_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("zones.zone_id", ondelete="SET NULL"))
    telemetry_age_sec: Mapped[int | None] = mapped_column(Integer)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)


class EquipmentTelemetry(Base):
    __tablename__ = "equipment_telemetry"

    telemetry_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    equipment_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("equipment.equipment_id", ondelete="CASCADE"), nullable=False
    )
    ts: Mapped[datetime] = mapped_column(nullable=False)
    speed_kmh: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    engine_rpm: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    engine_load_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    fuel_level_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    fuel_rate_lph: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    engine_temp_c: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    coolant_temp_c: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    oil_pressure_kpa: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    engine_hours: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    odometer_km: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    payload_t: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    battery_voltage: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    communication_quality: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    raw_data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class EquipmentState(Base):
    __tablename__ = "equipment_states"

    state_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    equipment_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("equipment.equipment_id", ondelete="CASCADE"), nullable=False
    )
    state: Mapped[EquipmentState] = mapped_column(nullable=False)
    start_time: Mapped[datetime] = mapped_column(nullable=False)
    end_time: Mapped[datetime | None] = mapped_column()
    duration_sec: Mapped[int | None] = mapped_column(Integer)
    zone_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("zones.zone_id", ondelete="SET NULL"))
    reason_code: Mapped[str | None] = mapped_column(String(100))
    reason_text: Mapped[str | None] = mapped_column(Text)
    reason_source: Mapped[str | None] = mapped_column(String(50))
    reason_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
