from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, Date, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.db.enums import EquipmentState, EquipmentType


class Operator(Base):
    __tablename__ = "operators"

    operator_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    employee_code: Mapped[str | None] = mapped_column(String(80), unique=True)
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    qualification: Mapped[str | None] = mapped_column(String(120))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Material(Base):
    __tablename__ = "materials"

    material_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str | None] = mapped_column(String(100))
    grade: Mapped[str | None] = mapped_column(String(100))
    density_t_m3: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)


class Equipment(Base):
    __tablename__ = "equipment"
    __table_args__ = (UniqueConstraint("site_id", "code"),)

    equipment_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    site_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("sites.site_id", ondelete="CASCADE"), nullable=False)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    type: Mapped[EquipmentType] = mapped_column(nullable=False)
    manufacturer: Mapped[str | None] = mapped_column(String(120))
    model: Mapped[str | None] = mapped_column(String(120))
    serial_number: Mapped[str | None] = mapped_column(String(120))
    capacity_t: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    fuel_capacity_l: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    commission_date: Mapped[date | None] = mapped_column(Date)
    current_state: Mapped[EquipmentState] = mapped_column(nullable=False, default=EquipmentState.UNKNOWN)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)

    site: Mapped["Site"] = relationship(back_populates="equipment")


from app.db.models.site import Site  # noqa: E402  circular for type hints
