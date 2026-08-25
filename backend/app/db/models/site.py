from datetime import date, datetime, time

from sqlalchemy import BigInteger, Boolean, Date, Double, ForeignKey, Integer, String, Text, Time, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class Site(Base):
    __tablename__ = "sites"

    site_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    region: Mapped[str | None] = mapped_column(String(150))
    timezone: Mapped[str] = mapped_column(String(80), nullable=False, default="Africa/Casablanca")
    latitude: Mapped[float | None] = mapped_column(Double)
    longitude: Mapped[float | None] = mapped_column(Double)
    # boundary geometry handled via raw SQL in seed; optional column
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False)

    shifts: Mapped[list["Shift"]] = relationship(back_populates="site")
    equipment: Mapped[list["Equipment"]] = relationship(back_populates="site")
    zones: Mapped[list["Zone"]] = relationship(back_populates="site")


class Shift(Base):
    __tablename__ = "shifts"
    __table_args__ = (UniqueConstraint("site_id", "shift_date", "name"),)

    shift_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    site_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("sites.site_id", ondelete="CASCADE"), nullable=False)
    shift_date: Mapped[date] = mapped_column(Date, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PLANNED")

    site: Mapped["Site"] = relationship(back_populates="shifts")
