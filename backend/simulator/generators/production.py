from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import ProductionActual


def record_dump_production(
    session: Session,
    shift_id: int,
    ts,
    payload_t: float,
    origin_zone_id: int | None,
    dest_zone_id: int | None,
    material_id: int | None,
    active_trucks: int,
    active_loaders: int,
) -> None:
    session.add(
        ProductionActual(
            shift_id=shift_id,
            ts=ts,
            source_zone_id=origin_zone_id,
            destination_zone_id=dest_zone_id,
            material_id=material_id,
            tonnes=Decimal(str(round(payload_t, 2))),
            cycles=1,
            active_trucks=active_trucks,
            active_loaders=active_loaders,
        )
    )
