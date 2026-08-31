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
    ("BANC_A", "Banc A", ZoneType.LOADING_BENCH, (-6.682, 32.668), 3, "#2F6FED",
     "Banc de chargement A. Destination prioritaire des camions affectés à l'excavatrice du panneau nord."),
    ("BANC_B", "Banc B", ZoneType.LOADING_BENCH, (-6.675, 32.655), 3, "#2F6FED",
     "Banc de chargement B. File d'attente camions sur le panneau sud."),
    ("CRUSHER", "Concasseur", ZoneType.CRUSHER, (-6.665, 32.662), 2, "#6B4FBF",
     "Concasseur primaire. Destination prioritaire du minerai haute teneur."),
    ("DUMP_N", "Dump North", ZoneType.DUMP_AREA, (-6.662, 32.670), 4, "#D97706",
     "Aire de déchargement nord — stériles et minerai hors spécification."),
    ("DUMP_S", "Dump South", ZoneType.DUMP_AREA, (-6.668, 32.652), 4, "#D97706",
     "Aire de déchargement sud — terril de stériles."),
    ("FUEL", "Fuel Station", ZoneType.FUEL_STATION, (-6.670, 32.665), 2, "#5B7C99",
     "Station fuel. Accès limité pendant le ravitaillement simultané de deux engins."),
    ("WORKSHOP", "Workshop", ZoneType.MAINTENANCE_WORKSHOP, (-6.678, 32.663), 2, "#7C8B84",
     "Atelier de maintenance mécanique. File d'attente hors production."),
    ("PARKING", "Parking", ZoneType.PARKING, (-6.672, 32.658), 8, "#00843D",
     "Parking engins — attente de poste et voie de report vers le concasseur."),
    ("BLAST_PAD", "Aire de tir", ZoneType.RESTRICTED_AREA, (-6.685, 32.660), 0, "#C0392B",
     "Aire de préparation de tir. Accès interdit pendant les opérations de minage."),
]

# Catalog distance represents the driven haul road (not straight-line geometry).
# road_quality is a documented simulator score from 0 (poor) to 100 (excellent).
ROAD_SPECS = [
    ("BANC_A", "CRUSHER", "RD-BA-CR", "R-03 Banc A — Concasseur", 4.2, 40, 4.0, 88),
    ("BANC_B", "CRUSHER", "RD-BB-CR", "R-04 Banc B — Concasseur", 5.6, 36, 6.5, 76),
    ("BANC_A", "DUMP_N", "RD-BA-DN", "R-07 Banc A — Dump nord", 7.4, 42, 3.0, 84),
    ("BANC_B", "DUMP_S", "RD-BB-DS", "R-08 Banc B — Dump sud", 4.8, 38, 5.0, 80),
    ("CRUSHER", "PARKING", "RD-CR-PK", "R-09 Concasseur — Parking", 3.2, 35, 2.0, 90),
    ("BANC_A", "FUEL", "RD-BA-FU", "R-10 Banc A — Fuel", 3.6, 35, 3.0, 86),
    ("BANC_B", "FUEL", "RD-BB-FU", "R-11 Banc B — Fuel", 3.9, 34, 4.5, 78),
    ("BANC_A", "WORKSHOP", "RD-BA-WS", "R-12 Banc A — Atelier", 4.1, 32, 3.5, 82),
    ("BANC_B", "WORKSHOP", "RD-BB-WS", "R-13 Banc B — Atelier", 4.3, 32, 5.0, 74),
    ("BANC_A", "PARKING", "R-05", "R-05 Banc A — Parking", 3.4, 38, 2.5, 85),
    ("PARKING", "CRUSHER", "R-06", "R-06 Parking — Concasseur", 2.8, 35, 2.0, 88),
]

# Extra vertices so catalog lines follow a haul corridor rather than a stick.
ROAD_WAYPOINTS = {
    "RD-BA-CR": [(-6.6788, 32.6672), (-6.6736, 32.6658), (-6.6688, 32.6636)],
    "R-05": [(-6.6794, 32.6658), (-6.6762, 32.6624), (-6.6734, 32.6596)],
    "R-06": [(-6.6698, 32.6572), (-6.6672, 32.6588), (-6.6658, 32.6606)],
    "RD-BB-CR": [(-6.6724, 32.6568), (-6.6686, 32.6584)],
}


def _box_polygon(lng: float, lat: float, d: float = 0.0018) -> WKTElement:
    wkt = (
        f"POLYGON(({lng - d} {lat - d}, {lng + d} {lat - d}, "
        f"{lng + d} {lat + d}, {lng - d} {lat + d}, {lng - d} {lat - d}))"
    )
    return WKTElement(wkt, srid=4326)


def _line(coords: list[tuple[float, float]]) -> WKTElement:
    parts = ", ".join(f"{lng} {lat}" for lng, lat in coords)
    return WKTElement(f"LINESTRING({parts})", srid=4326)


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
    for code, name, ztype, (lng, lat), cap, color, description in ZONE_SPECS:
        existing = session.scalar(select(Zone).where(Zone.site_id == site.site_id, Zone.code == code))
        if existing:
            existing.description = description
            zone_ids[code] = existing.zone_id
            zone_coords[code] = (lng, lat)
            continue
        z = Zone(
            site_id=site.site_id,
            code=code,
            name=name,
            type=ztype,
            description=description,
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

    for from_code, to_code, road_code, display_name, distance_km, speed_limit, grade_pct, quality in ROAD_SPECS:
        existing = session.scalar(
            select(HaulRoad).where(HaulRoad.site_id == site.site_id, HaulRoad.code == road_code)
        )
        lng1, lat1 = zone_coords[from_code]
        lng2, lat2 = zone_coords[to_code]
        coords = [(lng1, lat1), *ROAD_WAYPOINTS.get(road_code, []), (lng2, lat2)]
        if existing:
            existing.distance_km = Decimal(str(distance_km))
            existing.speed_limit_kmh = Decimal(str(speed_limit))
            existing.road_grade_pct = Decimal(str(grade_pct))
            existing.road_quality = Decimal(str(quality))
            existing.name = display_name
            existing.geometry = _line(coords)
            existing.metadata_ = {**(existing.metadata_ or {}), "simulated_catalog": True}
            continue
        session.add(
            HaulRoad(
                site_id=site.site_id,
                code=road_code,
                name=display_name,
                from_zone_id=zone_ids[from_code],
                to_zone_id=zone_ids[to_code],
                distance_km=Decimal(str(distance_km)),
                speed_limit_kmh=Decimal(str(speed_limit)),
                road_grade_pct=Decimal(str(grade_pct)),
                road_quality=Decimal(str(quality)),
                status="OPEN",
                geometry=_line(coords),
                metadata_={"simulated_catalog": True},
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
