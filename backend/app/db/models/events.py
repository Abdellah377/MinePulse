from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.enums import AlertSeverity, AlertSource, AlertStatus


class FuelEvent(Base):
    __tablename__ = "fuel_events"

    fuel_event_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    equipment_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("equipment.equipment_id", ondelete="CASCADE"), nullable=False
    )
    station_zone_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("zones.zone_id", ondelete="SET NULL"))
    ts: Mapped[datetime] = mapped_column(nullable=False)
    liters_added: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    fuel_before_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    fuel_after_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    duration_sec: Mapped[int | None] = mapped_column(Integer)
    operator_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("operators.operator_id", ondelete="SET NULL"))
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)


class MaintenanceEvent(Base):
    __tablename__ = "maintenance_events"

    maintenance_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    equipment_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("equipment.equipment_id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(30), nullable=False)
    component: Mapped[str | None] = mapped_column(String(150))
    description: Mapped[str | None] = mapped_column(Text)
    start_time: Mapped[datetime] = mapped_column(nullable=False)
    expected_end_time: Mapped[datetime | None] = mapped_column()
    actual_end_time: Mapped[datetime | None] = mapped_column()
    severity: Mapped[AlertSeverity | None] = mapped_column()
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="OPEN")
    planned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)


class DowntimeEvent(Base):
    __tablename__ = "downtime_events"

    downtime_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    equipment_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("equipment.equipment_id", ondelete="CASCADE"), nullable=False
    )
    start_time: Mapped[datetime] = mapped_column(nullable=False)
    end_time: Mapped[datetime | None] = mapped_column()
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String(60))
    confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    zone_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("zones.zone_id", ondelete="SET NULL"))
    estimated_loss_t: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)


class SystemEvent(Base):
    __tablename__ = "system_events"

    system_event_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    equipment_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("equipment.equipment_id", ondelete="CASCADE")
    )
    zone_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("zones.zone_id", ondelete="SET NULL"))
    ts: Mapped[datetime] = mapped_column(nullable=False)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False)
    source_system: Mapped[str | None] = mapped_column(String(80))
    message: Mapped[str | None] = mapped_column(Text)
    raw_data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class Alert(Base):
    __tablename__ = "alerts"

    alert_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False)
    predicted_for: Mapped[datetime | None] = mapped_column()
    source: Mapped[AlertSource] = mapped_column(nullable=False)
    severity: Mapped[AlertSeverity] = mapped_column(nullable=False)
    status: Mapped[AlertStatus] = mapped_column(nullable=False, default=AlertStatus.NEW)
    alert_type: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str] = mapped_column(String(220), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    equipment_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("equipment.equipment_id", ondelete="SET NULL")
    )
    zone_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("zones.zone_id", ondelete="SET NULL"))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    estimated_impact_t: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    estimated_impact_tph: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    assigned_to: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("operators.operator_id", ondelete="SET NULL"))
    acknowledged_at: Mapped[datetime | None] = mapped_column()
    resolved_at: Mapped[datetime | None] = mapped_column()
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
