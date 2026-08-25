"""Static world seed — site, fleet, zones, roads, operators, materials, shifts."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from decimal import Decimal

from geoalchemy2 import WKTElement
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.enums import EquipmentState, EquipmentType, ZoneType
from app.db.models import (
    Equipment,
    HaulRoad,
    Material,
    Operator,
    ProductionTarget,
    Shift,
    Site,
    Zone,
)
from simulator.clock import get_sim_logger

log = get_sim_logger()

# Khouribga Merah El Ahrach approximate bounds (SRID 4326)
SITE_CENTER = (-6.6735342, 32.6618173)

ZONE_SPECS = [
    ("BANC_A", "Banc A", ZoneType.LOADING_BENCH, (-6.682, 32.668), 3, "#2F6FED"),
    ("BANC_B", "Banc B", ZoneType.LOADING_BENCH, (-6.675, 32.655), 3, "#2F6FED"),
    ("CRUSHER", "Concasseur", ZoneType.CRUSHER, (-6.665, 32.662), 2, "#6B4FBF"),
    ("DUMP_N", "Dump North", ZoneType.DUMP_AREA, (-6.662, 32.670), 4, "#D97706"),
    ("DUMP_S", "Dump South", ZoneType.DUMP_AREA, (-6.668, 32.652), 4, "#D97706"),
    ("FUEL", "Fuel Station", ZoneType.FUEL_STATION, (-6.670, 32.665), 2, "#5B7C99"),
    ("WORKSHOP", "Workshop", ZoneType.MAINTENANCE_WORKSHOP, (-6.678, 32.663), 2, "#7C8B84"),
    ("PARKING", "Parking", ZoneType.PARKING, (-6.672, 32.658), 8, "#00843D"),
]

ROAD_PAIRS = [
    ("BANC_A", "CRUSHER", "RD-BA-CR"),
    ("BANC_B", "CRUSHER", "RD-BB-CR"),
    ("BANC_A", "DUMP_N", "RD-BA-DN"),
    ("BANC_B", "DUMP_S", "RD-BB-DS"),
    ("CRUSHER", "PARKING", "RD-CR-PK"),
    ("BANC_A", "FUEL", "RD-BA-FU"),
    ("BANC_B", "FUEL", "RD-BB-FU"),
    ("BANC_A", "WORKSHOP", "RD-BA-WS"),
    ("BANC_B", "WORKSHOP", "RD-BB-WS"),
]


def _box_polygon(lng: float, lat: float, d: float = 0.0018) -> WKTElement:
    wkt = (
        f"POLYGON(({lng - d} {lat - d}, {lng + d} {lat - d}, "
        f"{lng + d} {lat + d}, {lng - d} {lat + d}, {lng - d} {lat - d}))"
    )
    return WKTElement(wkt, srid=4326)


def _line(lng1: float, lat1: float, lng2: float, lat2: float) -> WKTElement:
    wkt = f"LINESTRING({lng1} {lat1}, {lng2} {lat2})"
    return WKTElement(wkt, srid=4326)


def _dist_km(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    # rough haversine approximation for prototype
    import math

    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    return round(2 * r * math.asin(math.sqrt(a)), 3)


def seed_static_world(session: Session) -> dict[str, int]:
    """Idempotent seed by code. Returns lookup maps."""
    from app.oem.schema import ensure_oem_schema

    ensure_oem_schema(session)
    now = datetime.now(timezone.utc)

    site = session.scalar(select(Site).where(Site.code == "MP-SIM-01"))
    if not site:
        site = Site(
            code="MP-SIM-01",
            name="MinePulse Simulation Site",
            region="Simulation Basin",
            timezone="Africa/Casablanca",
            latitude=SITE_CENTER[1],
            longitude=SITE_CENTER[0],
            active=True,
            created_at=now,
        )
        session.add(site)
        session.flush()
        lng, lat = SITE_CENTER
        d = 0.012
        session.execute(
            text(
                "UPDATE sites SET boundary = ST_SetSRID(ST_MakeEnvelope(:w,:s,:e,:n,4326),4326) "
                "WHERE site_id = :id"
            ),
            {"w": lng - d, "s": lat - d, "e": lng + d, "n": lat + d, "id": site.site_id},
        )
        log.info("Created site MP-SIM-01")
    else:
        log.info("Site MP-SIM-01 already exists")

    material = session.scalar(select(Material).where(Material.code == "PHOS_SIM"))
    if not material:
        material = Material(code="PHOS_SIM", name="Phosphate simulé", category="ORE", grade="SIM")
        session.add(material)
        session.flush()

    zone_ids: dict[str, int] = {}
    zone_coords: dict[str, tuple[float, float]] = {}
    for code, name, ztype, (lng, lat), cap, color in ZONE_SPECS:
        existing = session.scalar(select(Zone).where(Zone.site_id == site.site_id, Zone.code == code))
        if existing:
            zone_ids[code] = existing.zone_id
            zone_coords[code] = (lng, lat)
            continue
        z = Zone(
            site_id=site.site_id,
            code=code,
            name=name,
            type=ztype,
            description=f"Zone opérationnelle {name}",
            capacity=cap,
            status="ACTIVE",
            geometry=_box_polygon(lng, lat),
            metadata_={"color": color},
        )
        session.add(z)
        session.flush()
        zone_ids[code] = z.zone_id
        zone_coords[code] = (lng, lat)
        log.info("Created zone %s", code)

    for from_code, to_code, road_code in ROAD_PAIRS:
        existing = session.scalar(
            select(HaulRoad).where(HaulRoad.site_id == site.site_id, HaulRoad.code == road_code)
        )
        if existing:
            continue
        lng1, lat1 = zone_coords[from_code]
        lng2, lat2 = zone_coords[to_code]
        dist = _dist_km(lng1, lat1, lng2, lat2)
        session.add(
            HaulRoad(
                site_id=site.site_id,
                code=road_code,
                name=f"{from_code} → {to_code}",
                from_zone_id=zone_ids[from_code],
                to_zone_id=zone_ids[to_code],
                distance_km=Decimal(str(dist)),
                speed_limit_kmh=Decimal("40"),
                status="OPEN",
                geometry=_line(lng1, lat1, lng2, lat2),
            )
        )
    session.flush()

    fleet_specs: list[tuple[str, EquipmentType, str, float]] = []
    for i in range(1, 21):
        fleet_specs.append((f"TRK-{i:03d}", EquipmentType.HAUL_TRUCK, "CAT 793F", 180.0))
    for i in range(1, 4):
        fleet_specs.append((f"EXC-{i:03d}", EquipmentType.EXCAVATOR, "CAT 6060", 0))
    for i in range(1, 3):
        fleet_specs.append((f"LDR-{i:03d}", EquipmentType.LOADER, "CAT 994K", 0))
    for i in range(1, 3):
        fleet_specs.append((f"DOZ-{i:03d}", EquipmentType.DOZER, "CAT D11T", 0))
    fleet_specs.append(("GRD-001", EquipmentType.GRADER, "CAT 24M", 0))

    equip_ids: dict[str, int] = {}
    for code, etype, model, cap in fleet_specs:
        existing = session.scalar(select(Equipment).where(Equipment.code == code))
        if existing:
            equip_ids[code] = existing.equipment_id
            continue
        eq = Equipment(
            site_id=site.site_id,
            code=code,
            type=etype,
            manufacturer="CAT",
            model=model,
            capacity_t=Decimal(str(cap)) if cap else None,
            fuel_capacity_l=Decimal("4000") if etype == EquipmentType.HAUL_TRUCK else Decimal("800"),
            current_state=EquipmentState.PARKED if etype == EquipmentType.HAUL_TRUCK else EquipmentState.STOPPED_OPERATIONAL,
            active=True,
            metadata_={"simulated": True},
        )
        session.add(eq)
        session.flush()
        equip_ids[code] = eq.equipment_id

    for i in range(1, 11):
        code = f"OP-{i:03d}"
        if not session.scalar(select(Operator).where(Operator.employee_code == code)):
            session.add(Operator(employee_code=code, full_name=f"Opérateur {i}", qualification="Haul"))

    shift_date = date(2026, 1, 29)
    shift = session.scalar(
        select(Shift).where(Shift.site_id == site.site_id, Shift.shift_date == shift_date, Shift.name == "Poste matin")
    )
    if not shift:
        shift = Shift(
            site_id=site.site_id,
            shift_date=shift_date,
            name="Poste matin",
            start_time=time(6, 0),
            end_time=time(14, 0),
            status="ACTIVE",
        )
        session.add(shift)
        session.flush()

    target = session.scalar(select(ProductionTarget).where(ProductionTarget.shift_id == shift.shift_id))
    if not target:
        session.add(
            ProductionTarget(
                shift_id=shift.shift_id,
                material_id=material.material_id,
                target_tonnes=Decimal("42000"),
                target_cycles=240,
                target_utilization=Decimal("85"),
                target_cycle_min=Decimal("42"),
            )
        )

    from simulator.world import SimWorld

    SimWorld.write_control(
        {
            "status": "STOPPED",
            "speed": 30,
            "seed": 42,
            "scenario": "normal",
            "sim_now": datetime(2026, 1, 29, 6, 0, 0, tzinfo=timezone.utc).isoformat(),
        }
    )

    session.commit()
    log.info("Static seed complete — %d zones, %d equipment", len(zone_ids), len(equip_ids))
    return {"site_id": site.site_id, "shift_id": shift.shift_id, "zone_ids": zone_ids, "equip_ids": equip_ids}
