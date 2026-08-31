from datetime import datetime
from decimal import Decimal

from geoalchemy2 import Geometry
from sqlalchemy import BigInteger, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.db.enums import EquipmentState, ZoneType


class Zone(Base):
    __tablename__ = "zones"
    __table_args__ = (UniqueConstraint("site_id", "code"),)

    zone_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    site_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("sites.site_id", ondelete="CASCADE"), nullable=False)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    type: Mapped[ZoneType] = mapped_column(nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    capacity: Mapped[int | None] = mapped_column(Integer)
    priority: Mapped[int | None] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="ACTIVE")
    geometry = mapped_column(Geometry(geometry_type="POLYGON", srid=4326), nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)

    site: Mapped["Site"] = relationship(back_populates="zones")


class HaulRoad(Base):
    __tablename__ = "haul_roads"
    __table_args__ = (UniqueConstraint("site_id", "code"),)

    road_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    site_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("sites.site_id", ondelete="CASCADE"), nullable=False)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    from_zone_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("zones.zone_id", ondelete="SET NULL"))
    to_zone_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("zones.zone_id", ondelete="SET NULL"))
    distance_km: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    speed_limit_kmh: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    road_grade_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    road_quality: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="OPEN")
    description: Mapped[str | None] = mapped_column(Text)
    status_reason: Mapped[str | None] = mapped_column(String(40))
    status_note: Mapped[str | None] = mapped_column(Text)
    status_changed_at: Mapped[datetime | None] = mapped_column()
    geometry = mapped_column(Geometry(geometry_type="LINESTRING", srid=4326), nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)


class EquipmentAssignment(Base):
    __tablename__ = "equipment_assignments"

    assignment_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    shift_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("shifts.shift_id", ondelete="SET NULL"))
    truck_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("equipment.equipment_id", ondelete="CASCADE"))
    loader_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("equipment.equipment_id", ondelete="SET NULL"))
    operator_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("operators.operator_id", ondelete="SET NULL"))
    origin_zone_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("zones.zone_id", ondelete="SET NULL"))
    destination_zone_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("zones.zone_id", ondelete="SET NULL")
    )
    material_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("materials.material_id", ondelete="SET NULL"))
    assigned_at: Mapped[datetime] = mapped_column(nullable=False)
    started_at: Mapped[datetime | None] = mapped_column()
    completed_at: Mapped[datetime | None] = mapped_column()
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="FMS")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PLANNED")
    notes: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)


class Cycle(Base):
    __tablename__ = "cycles"

    cycle_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    shift_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("shifts.shift_id", ondelete="SET NULL"))
    truck_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("equipment.equipment_id", ondelete="CASCADE"), nullable=False)
    loader_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("equipment.equipment_id", ondelete="SET NULL"))
    origin_zone_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("zones.zone_id", ondelete="SET NULL"))
    destination_zone_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("zones.zone_id", ondelete="SET NULL")
    )
    material_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("materials.material_id", ondelete="SET NULL"))
    started_at: Mapped[datetime] = mapped_column(nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column()
    payload_t: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    distance_km: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    total_duration_sec: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="ACTIVE")
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)


class CycleStage(Base):
    __tablename__ = "cycle_stages"
    __table_args__ = (UniqueConstraint("cycle_id", "sequence_no"),)

    cycle_stage_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    cycle_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("cycles.cycle_id", ondelete="CASCADE"), nullable=False)
    stage: Mapped[EquipmentState] = mapped_column(nullable=False)
    start_time: Mapped[datetime] = mapped_column(nullable=False)
    end_time: Mapped[datetime | None] = mapped_column()
    duration_sec: Mapped[int | None] = mapped_column(Integer)
    zone_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("zones.zone_id", ondelete="SET NULL"))
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)


class Trip(Base):
    __tablename__ = "trips"

    trip_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    shift_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("shifts.shift_id", ondelete="SET NULL"))
    truck_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("equipment.equipment_id", ondelete="CASCADE"), nullable=False)
    cycle_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("cycles.cycle_id", ondelete="SET NULL"))
    material_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("materials.material_id", ondelete="SET NULL"))
    origin_zone_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("zones.zone_id", ondelete="SET NULL"))
    destination_zone_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("zones.zone_id", ondelete="SET NULL")
    )
    start_time: Mapped[datetime] = mapped_column(nullable=False)
    end_time: Mapped[datetime | None] = mapped_column()
    payload_t: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    distance_km: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="ACTIVE")
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)


from app.db.models.site import Site  # noqa: E402
