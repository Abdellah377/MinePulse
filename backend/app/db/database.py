from collections.abc import Generator

from sqlalchemy import Enum, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings
from app.db.enums import (
    AlertSeverity, AlertSource, AlertStatus, EquipmentState, EquipmentType,
    RecommendationStatus, ZoneType,
)

settings = get_settings()
DATABASE_URL = settings.database_url

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    class_=Session,
)


class Base(DeclarativeBase):
    # Match the existing PostgreSQL schema. Implicit enum names (e.g.
    # "alertsource") fail when psycopg bulk INSERT emits native type casts.
    type_annotation_map = {
        EquipmentType: Enum(EquipmentType, name="equipment_type"),
        EquipmentState: Enum(EquipmentState, name="equipment_state"),
        ZoneType: Enum(ZoneType, name="zone_type"),
        AlertSource: Enum(AlertSource, name="alert_source"),
        AlertSeverity: Enum(AlertSeverity, name="alert_severity"),
        AlertStatus: Enum(AlertStatus, name="alert_status"),
        RecommendationStatus: Enum(RecommendationStatus, name="recommendation_status"),
    }


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
