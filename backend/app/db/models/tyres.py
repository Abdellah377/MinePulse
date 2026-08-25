from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class TyreTelemetry(Base):
    __tablename__ = "tyre_telemetry"
    __table_args__ = (UniqueConstraint("equipment_id", "ts", "position"),)

    tyre_telemetry_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    equipment_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("equipment.equipment_id", ondelete="CASCADE"), nullable=False
    )
    ts: Mapped[datetime] = mapped_column(nullable=False)
    position: Mapped[str] = mapped_column(String(12), nullable=False)
    pressure_kpa: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    temperature_c: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
