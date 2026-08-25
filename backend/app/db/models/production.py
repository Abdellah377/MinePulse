from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, ForeignKey, Integer, Numeric
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class ProductionTarget(Base):
    __tablename__ = "production_targets"

    target_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    shift_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("shifts.shift_id", ondelete="CASCADE"), nullable=False)
    zone_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("zones.zone_id", ondelete="SET NULL"))
    material_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("materials.material_id", ondelete="SET NULL"))
    target_tonnes: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    target_cycles: Mapped[int | None] = mapped_column(Integer)
    target_utilization: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    target_cycle_min: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)


class ProductionActual(Base):
    __tablename__ = "production_actuals"

    production_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    shift_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("shifts.shift_id", ondelete="CASCADE"), nullable=False)
    ts: Mapped[datetime] = mapped_column(nullable=False)
    source_zone_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("zones.zone_id", ondelete="SET NULL"))
    destination_zone_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("zones.zone_id", ondelete="SET NULL")
    )
    material_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("materials.material_id", ondelete="SET NULL"))
    tonnes: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    cycles: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active_trucks: Mapped[int | None] = mapped_column(Integer)
    active_loaders: Mapped[int | None] = mapped_column(Integer)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
